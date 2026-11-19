import logging
from datetime import datetime, timezone
from typing import Optional

from openg2p_fastapi_common.service import BaseService
from sqlalchemy import func, select

from ..config import Settings
from ..errors import InvalidPolicyError, PolicyPendingError
from ..models import (
    AuditAction,
    Partner,
    PartnerPolicy,
    PartnerRequest,
    PartnerStatus,
    PolicyStatus,
    RequestStatus,
)
from ..schemas.policy import policy_label
from .audit_service import AuditService
from .partner_service import session_maker

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _key_of(row) -> tuple:
    """Policy key of a row / PolicyInput / PolicyRef / revoke dict."""
    get = row.get if isinstance(row, dict) else lambda f: getattr(row, f, None)
    if get("data_controller"):
        return ("data_controller", get("data_controller"))
    return ("use_case", get("use_case"))


def _key_is(key: tuple):
    """WHERE clause for one policy key."""
    kind, value = key
    return getattr(PartnerPolicy, kind) == value


def _details(key: tuple, **extra) -> dict:
    kind, value = key
    return {kind: value, **extra}


class PolicyService(BaseService):
    """Partner access policies, versioned per key: (partner, data controller)
    for a registry's scope policy, (partner, use case) for a use-case policy.

    Writes happen only inside a partner request's transaction (RequestService
    passes its session): a request adds ``pending`` versions, approval activates
    them (superseding the previous active one) and applies revocations,
    rejection marks them ``rejected``. Reads back the policy-fetch API, which is
    fail-closed like key fetch.
    """

    audit = AuditService.get_cached_component()

    # --- request side (caller's session, no commit) --------------------------

    async def check_proposal(
        self, session, partner_id: str, policies: list, revoke: list
    ) -> None:
        """Reject a proposal that clashes with an open one or revokes nothing.

        At most one pending change per policy key: a pending version or an open
        request revoking it both count.
        """
        proposed = [p.key for p in policies]
        revoked = [r.key for r in revoke]
        if not proposed and not revoked:
            raise InvalidPolicyError("Provide at least one policy or one policy to revoke.")
        both = [k for k in revoked if k in proposed]
        if both:
            raise InvalidPolicyError(
                f"Cannot both change and revoke the policy for {[policy_label(k) for k in both]}."
            )

        res = await session.execute(
            select(PartnerPolicy).where(
                PartnerPolicy.partner_id == partner_id,
                PartnerPolicy.status == PolicyStatus.pending.value,
            )
        )
        busy = {_key_of(p): p.request_id for p in res.scalars().all()}
        res = await session.execute(
            select(PartnerRequest).where(
                PartnerRequest.partner_id == partner_id,
                PartnerRequest.status == RequestStatus.created.value,
            )
        )
        for open_req in res.scalars().all():
            for r in open_req.revoke or []:
                busy.setdefault(_key_of(r), open_req.id)
        clash = [k for k in proposed + revoked if k in busy]
        if clash:
            raise PolicyPendingError(
                "A policy change is already pending for "
                + ", ".join(f"{policy_label(k)} (request {busy[k]})" for k in clash)
                + ". Approve or reject it first."
            )

        if revoked:
            active = await self._active_keys(session, partner_id)
            missing = [k for k in revoked if k not in active]
            if missing:
                raise InvalidPolicyError(
                    f"Cannot revoke {[policy_label(k) for k in missing]}: no active policy. "
                    f"Active: {sorted(policy_label(k) for k in active)}."
                )

    async def add_pending(
        self, session, partner_id: str, policies: list, request_id: str, actor: dict = None
    ) -> list[PartnerPolicy]:
        rows = []
        for p in policies:
            res = await session.execute(
                select(func.max(PartnerPolicy.version)).where(
                    PartnerPolicy.partner_id == partner_id, _key_is(p.key)
                )
            )
            version = (res.scalar() or 0) + 1
            row = PartnerPolicy(
                partner_id=partner_id,
                version=version,
                status=PolicyStatus.pending.value,
                request_id=request_id,
                created_by=(actor or {}).get("name"),
                **p.model_dump(),
            )
            session.add(row)
            rows.append(row)
            self.audit.record(
                session,
                action=AuditAction.policy_requested,
                entity_type="partner_policy",
                entity_id=row.id,
                partner_id=partner_id,
                request_id=request_id,
                actor=actor,
                details=_details(p.key, version=version),
            )
        return rows

    async def apply_approval(self, session, req: PartnerRequest, actor: dict = None) -> dict:
        """Activate the request's pending versions and apply its revocations."""
        now = _utcnow()
        actor_name = (actor or {}).get("name")
        activated, revoked = [], []

        for row in await self._request_rows(session, req.id):
            key = _key_of(row)
            for old in await self._active(session, req.partner_id, key):
                old.status = PolicyStatus.superseded.value
            row.status = PolicyStatus.active.value
            row.effective_from = now
            row.approved_by = actor_name
            activated.append(_details(key, version=row.version))
            self.audit.record(
                session,
                action=AuditAction.policy_approved,
                entity_type="partner_policy",
                entity_id=row.id,
                partner_id=req.partner_id,
                request_id=req.id,
                actor=actor,
                details=_details(key, version=row.version),
            )

        for ref in req.revoke or []:
            key = _key_of(ref)
            for old in await self._active(session, req.partner_id, key):
                old.status = PolicyStatus.revoked.value
                revoked.append(_details(key, version=old.version))
                self.audit.record(
                    session,
                    action=AuditAction.policy_revoked,
                    entity_type="partner_policy",
                    entity_id=old.id,
                    partner_id=req.partner_id,
                    request_id=req.id,
                    actor=actor,
                    details=_details(key, version=old.version),
                )
        return {"policies_activated": activated, "policies_revoked": revoked}

    async def apply_rejection(self, session, req: PartnerRequest, actor: dict = None) -> None:
        for row in await self._request_rows(session, req.id):
            row.status = PolicyStatus.rejected.value
            self.audit.record(
                session,
                action=AuditAction.policy_rejected,
                entity_type="partner_policy",
                entity_id=row.id,
                partner_id=req.partner_id,
                request_id=req.id,
                actor=actor,
                details=_details(_key_of(row), version=row.version),
            )

    async def _request_rows(self, session, request_id: str) -> list[PartnerPolicy]:
        res = await session.execute(
            select(PartnerPolicy).where(
                PartnerPolicy.request_id == request_id,
                PartnerPolicy.status == PolicyStatus.pending.value,
            )
        )
        return list(res.scalars().all())

    async def _active(self, session, partner_id: str, key: tuple) -> list[PartnerPolicy]:
        res = await session.execute(
            select(PartnerPolicy).where(
                PartnerPolicy.partner_id == partner_id,
                _key_is(key),
                PartnerPolicy.status == PolicyStatus.active.value,
            )
        )
        return list(res.scalars().all())

    async def _active_keys(self, session, partner_id: str) -> set:
        res = await session.execute(
            select(PartnerPolicy).where(
                PartnerPolicy.partner_id == partner_id,
                PartnerPolicy.status == PolicyStatus.active.value,
            )
        )
        return {_key_of(p) for p in res.scalars().all()}

    # --- reads ---------------------------------------------------------------

    async def list_for_partner(self, partner_id: str, all_versions: bool = False) -> list[PartnerPolicy]:
        """Staff view: active policies, or every version (newest first per key)."""
        async with session_maker()() as session:
            stmt = select(PartnerPolicy).where(PartnerPolicy.partner_id == partner_id)
            if not all_versions:
                stmt = stmt.where(PartnerPolicy.status == PolicyStatus.active.value)
            res = await session.execute(stmt.order_by(*_ORDER, PartnerPolicy.version.desc()))
            return list(res.scalars().all())

    async def get_servable_policies(
        self,
        partner_id: str,
        data_controller: Optional[str] = None,
        use_case: Optional[str] = None,
    ) -> list[PartnerPolicy] | None:
        """Active policies of an ACTIVE partner, else None (fail-closed).

        No filter = all its active policies (registries and use cases).
        ``data_controller`` = that registry's policy ("" = its use-case
        policies); ``use_case`` = that use case's policy. An unknown / non-active
        partner and one with no matching active policy all return None.
        """
        async with session_maker()() as session:
            res = await session.execute(
                select(Partner).where(Partner.partner_id == partner_id)
            )
            partner = res.scalars().first()
            if not partner or partner.status != PartnerStatus.active.value:
                return None
            stmt = _filtered(
                select(PartnerPolicy).where(
                    PartnerPolicy.partner_id == partner_id,
                    PartnerPolicy.status == PolicyStatus.active.value,
                ),
                data_controller,
                use_case,
            )
            res = await session.execute(stmt.order_by(*_ORDER))
            return list(res.scalars().all()) or None

    async def list_servable(
        self, use_case: Optional[str] = None, data_controller: Optional[str] = None
    ) -> list[PartnerPolicy]:
        """Active policies of active partners, optionally filtered (for listings)."""
        async with session_maker()() as session:
            stmt = _filtered(
                select(PartnerPolicy)
                .join(Partner, Partner.partner_id == PartnerPolicy.partner_id)
                .where(
                    Partner.status == PartnerStatus.active.value,
                    PartnerPolicy.status == PolicyStatus.active.value,
                ),
                data_controller,
                use_case,
            )
            stmt = stmt.order_by(PartnerPolicy.partner_id, *_ORDER)
            return list((await session.execute(stmt)).scalars().all())


# Registries first (by controller), then use cases (by name).
_ORDER = (
    PartnerPolicy.data_controller.is_(None),
    PartnerPolicy.data_controller,
    PartnerPolicy.use_case,
)


def _filtered(stmt, data_controller: Optional[str], use_case: Optional[str]):
    """Apply the read filters: data_controller ("" = use-case policies), use_case."""
    if data_controller is not None:
        dc = data_controller.strip()
        stmt = stmt.where(
            PartnerPolicy.data_controller == dc if dc else PartnerPolicy.data_controller.is_(None)
        )
    if use_case:
        stmt = stmt.where(PartnerPolicy.use_case == use_case.strip())
    return stmt
