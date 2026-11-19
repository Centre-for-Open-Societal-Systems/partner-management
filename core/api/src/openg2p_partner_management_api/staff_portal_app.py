# ruff: noqa: E402
import asyncio
import logging

from .config import Settings

_config = Settings.get_config()

from openg2p_fastapi_common.app import Initializer as BaseInitializer

from .audit_middleware import AuditMiddleware
from .controllers import AdminPartnerController, AdminRequestController
from .bootstrap import bootstrap_partners
from .migrations import migrate_all
from .services import (
    AuditService,
    CatalogueService,
    KeyService,
    PartnerService,
    PolicyService,
    RequestService,
)

_logger = logging.getLogger(_config.logging_default_logger_name)


class Initializer(BaseInitializer):
    """staff-portal-api: the staff/admin-facing service.

    Serves onboarding, key-rotation, policy and partner-management endpoints, all guarded
    by a Keycloak staff-realm JWT (see auth.PartnerManagerAuth). Backs the admin
    UI. Does not expose the public key- / policy-fetch routes.
    """

    def initialize(self, **kwargs):
        super().initialize()
        KeyService()
        PartnerService()
        AuditService()
        CatalogueService()
        PolicyService()
        RequestService()
        AdminRequestController().post_init()
        AdminPartnerController().post_init()
        # Central Audit Manager trail (config-gated, non-blocking).
        self.return_app().add_middleware(
            AuditMiddleware,
            audit_manager_url=_config.audit_manager_url,
            enabled=_config.audit_enabled,
            timeout_seconds=_config.audit_timeout_seconds,
            source=_config.audit_source,
            module=_config.audit_module,
            client_id=_config.auth_admin_client_id,
            audit_anonymous_failures=_config.audit_anonymous_failures,
        )

    def migrate_database(self, args):
        super().migrate_database(args)
        asyncio.run(_migrate_and_bootstrap())


async def _migrate_and_bootstrap():
    await migrate_all()
    # Partners onboarded at install (bootstrap_partners); needs the tables above.
    await bootstrap_partners()
