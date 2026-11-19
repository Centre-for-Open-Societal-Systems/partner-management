import logging

from openg2p_fastapi_common.context import dbengine
from sqlalchemy import text

from .config import Settings
from .models import AuditEvent, Partner, PartnerKey, PartnerPolicy, PartnerRequest

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


async def migrate_all():
    """Create all Partner Management tables (idempotent).

    Shared by both service entrypoints (staff-portal-api and partner-api) since
    they run against the same database.
    """
    _logger.info("Migrating Partner Management database")
    await Partner.create_migrate()
    await PartnerKey.create_migrate()
    await PartnerRequest.create_migrate()
    await PartnerPolicy.create_migrate()
    await AuditEvent.create_migrate()
    await _alter_existing_tables()


# create_all() neither adds nor drops columns of an existing table: do it here
# (no-ops on a fresh database). PostgreSQL only (tests create fresh SQLite tables).
_ADDED_COLUMNS = [
    ("pm_partner_requests", "warnings", "JSONB DEFAULT '[]'::jsonb"),
    ("pm_partner_requests", "revoke_policies", "JSONB DEFAULT '[]'::jsonb"),
    ("pm_partner_policies", "use_case", "VARCHAR(255)"),
    ("pm_partner_policies", "allow_partner_consents", "BOOLEAN NOT NULL DEFAULT false"),
    ("pm_partner_policies", "allow_assisted_confirmation", "BOOLEAN NOT NULL DEFAULT false"),
    ("pm_partners", "keys_from_jwks_url", "BOOLEAN NOT NULL DEFAULT false"),
    ("pm_partner_requests", "keys_from_jwks_url", "BOOLEAN NOT NULL DEFAULT false"),
]
# Replaced by one policy per use case (use_case) and revoke_policies.
_DROPPED_COLUMNS = [
    ("pm_partner_policies", "allowed_use_cases"),
    ("pm_partner_requests", "revoke_data_controllers"),
]


CLEAR_USE_CASE_PURPOSES = (
    "UPDATE pm_partner_policies SET allowed_purposes = '[]' "
    "WHERE use_case IS NOT NULL AND allowed_purposes IS DISTINCT FROM '[]'::jsonb"
)


async def _alter_existing_tables():
    engine = dbengine.get()
    if engine.dialect.name != "postgresql":
        return
    async with engine.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}"))
        for table, column in _DROPPED_COLUMNS:
            await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}"))
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_pm_partner_policies_use_case "
                "ON pm_partner_policies (use_case)"
            )
        )
        # A policy of the old shape (all use cases in one row) has neither key:
        # retire it so it is never served; re-grant each use case as its own policy.
        await conn.execute(
            text(
                "UPDATE pm_partner_policies SET status = 'revoked' "
                "WHERE data_controller IS NULL AND use_case IS NULL "
                "AND status IN ('active', 'pending')"
            )
        )
        # A use-case policy lists no purposes (granting a use case grants its
        # purpose): clear those set before that rule, in every version.
        await conn.execute(text(CLEAR_USE_CASE_PURPOSES))
