import logging
from datetime import datetime

from openg2p_fastapi_common.context import dbengine
from openg2p_fastapi_common.service import BaseService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..config import Settings
from ..errors import PartnerNotFoundError
from ..models import AuditAction, KeyStatus, Partner, PartnerKey, PartnerStatus
from .key_service import KeyService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


def session_maker():
    return async_sessionmaker(dbengine.get(), expire_on_commit=False)


class PartnerService(BaseService):
    """Read/lifecycle operations on partners and the fail-closed key lookup."""

    async def get_partner(self, partner_id: str) -> Partner | None:
        async with session_maker()() as session:
            res = await session.execute(
                select(Partner).where(Partner.partner_id == partner_id)
            )
            return res.scalars().first()

    async def list_partners(self, status: str = None) -> list[Partner]:
        async with session_maker()() as session:
            stmt = select(Partner).order_by(Partner.created_at.desc())
            if status:
                stmt = stmt.where(Partner.status == status)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def list_keys(self, partner_id: str) -> list[PartnerKey]:
        """All keys (any status) for the admin console."""
        async with session_maker()() as session:
            res = await session.execute(
                select(PartnerKey)
                .where(PartnerKey.partner_id == partner_id)
                .order_by(PartnerKey.created_at.desc())
            )
            return list(res.scalars().all())

    async def set_status(self, partner_id: str, status: PartnerStatus, actor: dict = None) -> Partner:
        # Lazy import avoids a module-load cycle (audit_service imports this module).
        from .audit_service import AuditService

        async with session_maker()() as session:
            res = await session.execute(
                select(Partner).where(Partner.partner_id == partner_id)
            )
            partner = res.scalars().first()
            if not partner:
                raise PartnerNotFoundError(partner_id)
            previous = partner.status
            partner.status = status.value
            if status == PartnerStatus.active:
                partner.approved_by = (actor or {}).get("name")

            action = (
                AuditAction.partner_disabled
                if status == PartnerStatus.disabled
                else AuditAction.partner_enabled
                if status == PartnerStatus.active
                else None
            )
            if action:
                AuditService.get_component().record(
                    session,
                    action=action,
                    entity_type="partner",
                    entity_id=partner.id,
                    partner_id=partner_id,
                    actor=actor,
                    details={"from": previous, "to": status.value},
                )
            await session.commit()
            await session.refresh(partner)
            return partner

    async def get_servable_keys(self, partner_id: str) -> list[dict] | None:
        """Return active, currently-valid keys for an ACTIVE partner, else None.

        Fail-closed: a missing partner, a non-active partner (created/disabled),
        or a partner with no currently-valid active keys all return None, and the
        caller maps that to a uniform "not available" response. For a partner
        with keys_from_jwks_url, the keys at its JWKS URL are added (cached).
        """
        async with session_maker()() as session:
            res = await session.execute(
                select(Partner).where(Partner.partner_id == partner_id)
            )
            partner = res.scalars().first()
            if not partner or partner.status != PartnerStatus.active.value:
                return None

            res = await session.execute(
                select(PartnerKey).where(
                    PartnerKey.partner_id == partner_id,
                    PartnerKey.status == KeyStatus.active.value,
                )
            )
            rows = res.scalars().all()

            live = (
                await KeyService.get_component().live_keys(partner.jwks_url)
                if partner.keys_from_jwks_url and partner.jwks_url
                else []
            )

        now = datetime.now()
        keys = []
        for row in rows:
            if row.not_before and _naive(row.not_before) > now:
                continue
            if row.not_after and _naive(row.not_after) < now:
                continue
            keys.append(
                {
                    "partner_id": row.partner_id,
                    "kid": row.kid,
                    "algorithm": row.algorithm,
                    "public_key": row.public_key,
                    "not_before": row.not_before,
                    "not_after": row.not_after,
                }
            )
        # Keys read from the partner's JWKS URL; a stored key with the same kid wins.
        stored_kids = {k["kid"] for k in keys}
        keys += [
            {"partner_id": partner_id, **k} for k in live if k["kid"] not in stored_kids
        ]
        return keys or None


def _naive(dt: datetime) -> datetime:
    """Compare tz-aware DB values against naive utcnow consistently."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt
