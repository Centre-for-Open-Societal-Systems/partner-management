import logging
from datetime import datetime

from openg2p_fastapi_common.context import dbengine
from openg2p_fastapi_common.service import BaseService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..config import Settings
from ..errors import (
    InvalidKeyError,
    InvalidPolicyError,
    PartnerExistsError,
    PartnerNotFoundError,
    RequestNotFoundError,
    RequestNotOpenError,
)
from ..models import (
    AuditAction,
    KeyStatus,
    Partner,
    PartnerKey,
    PartnerRequest,
    PartnerStatus,
    RequestStatus,
    RequestType,
)
from ..schemas.policy import policy_label
from .audit_service import AuditService
from .catalogue_service import CatalogueService
from .key_service import KeyService
from .partner_service import PartnerService
from .policy_service import PolicyService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


def _sm():
    return async_sessionmaker(dbengine.get(), expire_on_commit=False)


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


class RequestService(BaseService):
    """Creates onboarding / key-update / policy requests and applies them on approval.

    Key material is normalised and validated up front (at request creation), so
    approval is a cheap, deterministic apply. In v1 the admin both files and
    approves; the same apply path is reused for a future AWE webhook.
    """

    keys = KeyService.get_cached_component()
    partners = PartnerService.get_cached_component()
    audit = AuditService.get_cached_component()
    policies = PolicyService.get_cached_component()
    catalogue = CatalogueService.get_cached_component()

    # --- creation ------------------------------------------------------------

    async def _collect_and_normalize(self, key_inputs, jwks_url, do_import) -> list[dict]:
        normalized: list[dict] = []
        for k in key_inputs:
            nk = self.keys.normalize(
                public_key=k.public_key,
                jwk=k.jwk,
                kid=k.kid,
                algorithm=k.algorithm.value if k.algorithm else None,
            )
            normalized.append(nk.as_dict(k.not_before, k.not_after))

        if do_import:
            if not jwks_url:
                raise InvalidKeyError("import_from_jwks_url is set but jwks_url is empty.")
            for fetched in await self.keys.fetch_jwks_keys(jwks_url):
                nk = self.keys.normalize(jwk=fetched["jwk"], kid=fetched.get("kid"))
                normalized.append(nk.as_dict())

        # De-duplicate by fingerprint (last wins, keeping validity from that entry).
        deduped: dict[str, dict] = {}
        for n in normalized:
            deduped[n["key_fingerprint"]] = n
        return list(deduped.values())

    async def _check_catalogue(self, policies) -> list[str]:
        """Policies against the configured catalogue sources (rejects unknown names)."""
        if self.catalogue is None:  # not initialised (e.g. a partial app)
            return []
        return await self.catalogue.check_policies(policies)

    @staticmethod
    def _signing_alg_warnings(policies, key_algs: set, whose: str) -> list[str]:
        """Warn when a policy allows an algorithm none of the partner's keys uses.

        Only for algorithms the request names (not the default); never blocks: a
        key of that type may be added later.
        """
        warnings = []
        for p in policies:
            if "allowed_signing_algs" not in p.model_fields_set:
                continue
            unmatched = [a for a in p.allowed_signing_algs if a not in key_algs]
            if unmatched:
                warnings.append(
                    f"Policy for {policy_label(p.key)}: signing algorithms {unmatched} match none of "
                    f"{whose} ({', '.join(sorted(key_algs)) or 'none'}); the partner cannot "
                    "sign with them until it has such a key."
                )
        return warnings

    async def create_onboarding(self, data, actor: dict = None) -> PartnerRequest:
        if await self.partners.get_partner(data.partner_id):
            raise PartnerExistsError(data.partner_id)

        proposed = await self._collect_and_normalize(
            data.keys, data.jwks_url, data.import_from_jwks_url
        )
        if not proposed and not data.keys_from_jwks_url:
            raise InvalidKeyError(
                "At least one public key is required to onboard a partner "
                "(or read its keys from its JWKS URL: keys_from_jwks_url)."
            )
        warnings = await self._check_catalogue(data.policies)
        warnings += self._signing_alg_warnings(
            data.policies, {k["algorithm"] for k in proposed}, "the proposed keys' algorithms"
        )

        actor_name = (actor or {}).get("name")
        async with _sm()() as session:
            partner = Partner(
                partner_id=data.partner_id,
                name=data.name,
                org_name=data.org_name,
                description=data.description,
                jwks_url=data.jwks_url,
                keys_from_jwks_url=data.keys_from_jwks_url,
                status=PartnerStatus.created.value,
                created_by=actor_name,
            )
            req = PartnerRequest(
                request_type=RequestType.onboarding.value,
                partner_id=data.partner_id,
                name=data.name,
                org_name=data.org_name,
                description=data.description,
                jwks_url=data.jwks_url,
                keys_from_jwks_url=data.keys_from_jwks_url,
                proposed_keys=proposed,
                revoke_kids=[],
                proposed_policies=[p.model_dump() for p in data.policies],
                revoke=[],
                warnings=warnings,
                status=RequestStatus.created.value,
                submitted_by=actor_name,
            )
            session.add(partner)
            session.add(req)
            # Pending version 1 of each policy, activated with the partner.
            await self.policies.add_pending(
                session, data.partner_id, data.policies, req.id, actor=actor
            )
            self.audit.record(
                session,
                action=AuditAction.partner_created,
                entity_type="partner",
                entity_id=partner.id,
                partner_id=data.partner_id,
                request_id=req.id,
                actor=actor,
                details={"status": PartnerStatus.created.value},
            )
            self.audit.record(
                session,
                action=AuditAction.request_submitted,
                entity_type="partner_request",
                entity_id=req.id,
                partner_id=data.partner_id,
                request_id=req.id,
                actor=actor,
                details={
                    "type": RequestType.onboarding.value,
                    "keys": len(proposed),
                    **({"keys_from_jwks_url": data.jwks_url} if data.keys_from_jwks_url else {}),
                    "policies": [p.key[1] for p in data.policies],
                    **({"warnings": warnings} if warnings else {}),
                },
            )
            await session.commit()
            await session.refresh(req)
            return req

    async def create_key_update(self, data, actor: dict = None) -> PartnerRequest:
        partner = await self.partners.get_partner(data.partner_id)
        if not partner:
            raise PartnerNotFoundError(data.partner_id)

        # Only the partner's current (non-revoked) kids can be revoked — the same
        # set the UI offers as a multi-select.
        revocable = {
            k.kid
            for k in await self.partners.list_keys(data.partner_id)
            if k.status != KeyStatus.revoked.value
        }
        unknown = sorted(set(data.revoke_kids or []) - revocable)
        if unknown:
            raise InvalidKeyError(
                f"Cannot revoke {unknown}: not a current key of partner "
                f"'{data.partner_id}'. Revocable: {sorted(revocable)}."
            )

        proposed = await self._collect_and_normalize(
            data.keys, data.jwks_url, data.import_from_jwks_url
        )
        if not proposed and not data.revoke_kids:
            raise InvalidKeyError("Provide at least one key to add or one kid to revoke.")

        async with _sm()() as session:
            req = PartnerRequest(
                request_type=RequestType.key_update.value,
                partner_id=data.partner_id,
                description=data.description,
                jwks_url=data.jwks_url,
                proposed_keys=proposed,
                revoke_kids=list(data.revoke_kids or []),
                status=RequestStatus.created.value,
                submitted_by=(actor or {}).get("name"),
            )
            session.add(req)
            self.audit.record(
                session,
                action=AuditAction.request_submitted,
                entity_type="partner_request",
                entity_id=req.id,
                partner_id=data.partner_id,
                request_id=req.id,
                actor=actor,
                details={
                    "type": RequestType.key_update.value,
                    "keys_proposed": [k["kid"] for k in proposed],
                    "revoke_kids": list(data.revoke_kids or []),
                },
            )
            await session.commit()
            await session.refresh(req)
            return req

    async def create_policy(self, data, actor: dict = None) -> PartnerRequest:
        partner = await self.partners.get_partner(data.partner_id)
        if not partner:
            raise PartnerNotFoundError(data.partner_id)
        # Only approved partners: onboarding policies cover a 'created' partner.
        if partner.status == PartnerStatus.created.value:
            raise InvalidPolicyError(
                f"Partner '{data.partner_id}' is not approved yet; approve its onboarding "
                "request (which carries its initial policies) before changing its policies."
            )
        if partner.status == PartnerStatus.disabled.value:
            raise InvalidPolicyError(
                f"Partner '{data.partner_id}' is disabled; enable it before changing its policies."
            )

        warnings = await self._check_catalogue(data.policies)
        active_algs = {
            k.algorithm
            for k in await self.partners.list_keys(data.partner_id)
            if k.status == KeyStatus.active.value
        }
        warnings += self._signing_alg_warnings(
            data.policies, active_algs, "the partner's active keys' algorithms"
        )
        async with _sm()() as session:
            await self.policies.check_proposal(
                session, data.partner_id, data.policies, data.revoke
            )
            req = PartnerRequest(
                request_type=RequestType.policy.value,
                partner_id=data.partner_id,
                description=data.description,
                proposed_keys=[],
                revoke_kids=[],
                proposed_policies=[p.model_dump() for p in data.policies],
                revoke=[r.as_dict() for r in data.revoke],
                warnings=warnings,
                status=RequestStatus.created.value,
                submitted_by=(actor or {}).get("name"),
            )
            session.add(req)
            await self.policies.add_pending(
                session, data.partner_id, data.policies, req.id, actor=actor
            )
            self.audit.record(
                session,
                action=AuditAction.request_submitted,
                entity_type="partner_request",
                entity_id=req.id,
                partner_id=data.partner_id,
                request_id=req.id,
                actor=actor,
                details={
                    "type": RequestType.policy.value,
                    "policies": [p.key[1] for p in data.policies],
                    "revoke": [r.key[1] for r in data.revoke],
                    **({"warnings": warnings} if warnings else {}),
                },
            )
            await session.commit()
            await session.refresh(req)
            return req

    # --- reads ---------------------------------------------------------------

    async def get_request(self, request_id: str) -> PartnerRequest:
        async with _sm()() as session:
            req = await session.get(PartnerRequest, request_id)
            if not req:
                raise RequestNotFoundError(request_id)
            return req

    async def list_requests(
        self, status: str = None, partner_id: str = None, request_type: str = None
    ) -> list[PartnerRequest]:
        async with _sm()() as session:
            stmt = select(PartnerRequest).order_by(PartnerRequest.created_at.desc())
            if status:
                stmt = stmt.where(PartnerRequest.status == status)
            if request_type:
                stmt = stmt.where(PartnerRequest.request_type == request_type)
            if partner_id:
                stmt = stmt.where(PartnerRequest.partner_id == partner_id)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    # --- decisions -----------------------------------------------------------

    async def approve(self, request_id: str, actor: dict = None, notes: str = None) -> PartnerRequest:
        actor_name = (actor or {}).get("name")
        async with _sm()() as session:
            req = await session.get(PartnerRequest, request_id)
            if not req:
                raise RequestNotFoundError(request_id)
            if req.status != RequestStatus.created.value:
                raise RequestNotOpenError(
                    f"Request is '{req.status}', only 'created' requests can be approved."
                )

            res = await session.execute(
                select(Partner).where(Partner.partner_id == req.partner_id)
            )
            partner = res.scalars().first()
            if not partner:
                raise PartnerNotFoundError(req.partner_id)

            # Onboarding flips the partner active; key_update leaves status as-is.
            if req.request_type == RequestType.onboarding.value:
                partner.status = PartnerStatus.active.value
                partner.approved_by = actor_name
                self.audit.record(
                    session,
                    action=AuditAction.partner_approved,
                    entity_type="partner",
                    entity_id=partner.id,
                    partner_id=req.partner_id,
                    request_id=req.id,
                    actor=actor,
                    details={"from": PartnerStatus.created.value, "to": PartnerStatus.active.value},
                )

            added, revoked = [], []
            for pk in req.proposed_keys or []:
                await self._upsert_key(session, req.partner_id, pk)
                added.append(pk["kid"])
                self.audit.record(
                    session,
                    action=AuditAction.key_added,
                    entity_type="partner_key",
                    entity_id=pk["kid"],
                    partner_id=req.partner_id,
                    request_id=req.id,
                    actor=actor,
                    details={"kid": pk["kid"], "algorithm": pk.get("algorithm")},
                )

            for kid in req.revoke_kids or []:
                if await self._revoke_key(session, req.partner_id, kid):
                    revoked.append(kid)
                    self.audit.record(
                        session,
                        action=AuditAction.key_revoked,
                        entity_type="partner_key",
                        entity_id=kid,
                        partner_id=req.partner_id,
                        request_id=req.id,
                        actor=actor,
                        details={"kid": kid},
                    )

            policy_changes = await self.policies.apply_approval(session, req, actor=actor)

            req.status = RequestStatus.approved.value
            req.reviewed_by = actor_name
            req.review_notes = notes
            self.audit.record(
                session,
                action=AuditAction.request_approved,
                entity_type="partner_request",
                entity_id=req.id,
                partner_id=req.partner_id,
                request_id=req.id,
                actor=actor,
                details={"kids_added": added, "kids_revoked": revoked, **policy_changes},
            )
            await session.commit()
            await session.refresh(req)
            return req

    async def reject(self, request_id: str, actor: dict = None, notes: str = None) -> PartnerRequest:
        async with _sm()() as session:
            req = await session.get(PartnerRequest, request_id)
            if not req:
                raise RequestNotFoundError(request_id)
            if req.status != RequestStatus.created.value:
                raise RequestNotOpenError(
                    f"Request is '{req.status}', only 'created' requests can be rejected."
                )
            # A rejected onboarding leaves the partner in 'created' (never served);
            # the admin can disable or resubmit. No keys were materialised; its
            # pending policy versions become 'rejected'.
            await self.policies.apply_rejection(session, req, actor=actor)
            req.status = RequestStatus.rejected.value
            req.reviewed_by = (actor or {}).get("name")
            req.review_notes = notes
            self.audit.record(
                session,
                action=AuditAction.request_rejected,
                entity_type="partner_request",
                entity_id=req.id,
                partner_id=req.partner_id,
                request_id=req.id,
                actor=actor,
                details={"type": req.request_type, "notes": notes},
            )
            await session.commit()
            await session.refresh(req)
            return req

    # --- apply helpers -------------------------------------------------------

    async def _upsert_key(self, session, partner_id: str, pk: dict):
        res = await session.execute(
            select(PartnerKey).where(
                PartnerKey.partner_id == partner_id, PartnerKey.kid == pk["kid"]
            )
        )
        existing = res.scalars().first()
        if existing:
            existing.algorithm = pk["algorithm"]
            existing.public_key = pk["public_key"]
            existing.key_fingerprint = pk.get("key_fingerprint")
            existing.status = KeyStatus.active.value
            existing.not_before = _parse_dt(pk.get("not_before"))
            existing.not_after = _parse_dt(pk.get("not_after"))
        else:
            session.add(
                PartnerKey(
                    partner_id=partner_id,
                    kid=pk["kid"],
                    algorithm=pk["algorithm"],
                    public_key=pk["public_key"],
                    key_fingerprint=pk.get("key_fingerprint"),
                    status=KeyStatus.active.value,
                    not_before=_parse_dt(pk.get("not_before")),
                    not_after=_parse_dt(pk.get("not_after")),
                )
            )

    async def _revoke_key(self, session, partner_id: str, kid: str) -> bool:
        res = await session.execute(
            select(PartnerKey).where(
                PartnerKey.partner_id == partner_id, PartnerKey.kid == kid
            )
        )
        key = res.scalars().first()
        if key and key.status != KeyStatus.revoked.value:
            key.status = KeyStatus.revoked.value
            return True
        return False
