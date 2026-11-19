# ruff: noqa: E402
import asyncio
import logging

from .config import Settings

_config = Settings.get_config()

from openg2p_fastapi_common.app import Initializer as BaseInitializer

from .controllers import KeyFetchController, PolicyFetchController
from .migrations import migrate_all
from .services import KeyService, PartnerService, PolicyService

_logger = logging.getLogger(_config.logging_default_logger_name)


class Initializer(BaseInitializer):
    """partner-api: the inter-service key- and policy-fetch service.

    Exposes only the unauthenticated fetch routes (``/keys/...``, ``/policies...``)
    that other OpenG2P modules call to obtain partner public keys and policies.
    No admin routes, no auth dependency. Runs on the cluster-internal gateway.
    """

    def initialize(self, **kwargs):
        super().initialize()
        KeyService()
        PartnerService()
        PolicyService()
        KeyFetchController().post_init()
        PolicyFetchController().post_init()

    def migrate_database(self, args):
        super().migrate_database(args)
        asyncio.run(migrate_all())
