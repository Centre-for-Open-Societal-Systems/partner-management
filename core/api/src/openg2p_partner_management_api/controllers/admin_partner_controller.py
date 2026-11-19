import logging
from typing import Annotated, Optional

from fastapi import Depends
from openg2p_fastapi_common.controller import BaseController

from ..auth import AuthCredentials, PartnerManagerAuth
from ..config import Settings
from ..errors import PartnerNotFoundError
from ..models import (
    IDENTIFIER_HINT,
    IDENTIFIER_PATTERN,
    FetchType,
    KeyStatus,
    PartnerStatus,
    PolicyStatus,
    RequestStatus,
    RequestType,
    SigningAlgorithm,
)
from ..schemas import (
    AuditEventListResponse,
    AuditEventResponse,
    CatalogueResponse,
    KeyResponse,
    MetadataResponse,
    PartnerActionResponse,
    PartnerListResponse,
    PartnerResponse,
    PolicyResponse,
)
from ..schemas.policy import allowed_signing_algorithms
from ..services import (
    AuditService,
    CatalogueService,
    KeyService,
    PartnerService,
    PolicyService,
)

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)

_admin_auth = PartnerManagerAuth()


class AdminPartnerController(BaseController):
    """Staff-realm APIs to browse partners and toggle their availability."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.partners = PartnerService.get_component()
        self.audit = AuditService.get_component()
        self.keys = KeyService.get_component()
        self.policies = PolicyService.get_component()
        self.catalogue = CatalogueService.get_component()
        self.router.tags += ["Admin: Partners"]

        self.router.add_api_route(
            "/metadata",
            self.get_metadata,
            methods=["GET"],
            responses={200: {"model": MetadataResponse}},
        )
        self.router.add_api_route(
            "/catalogue",
            self.get_catalogue,
            methods=["GET"],
            responses={200: {"model": CatalogueResponse}},
        )
        self.router.add_api_route(
            "/partners",
            self.list_partners,
            methods=["GET"],
            responses={200: {"model": PartnerListResponse}},
        )
        self.router.add_api_route(
            "/partners/{partner_id}",
            self.get_partner,
            methods=["GET"],
            responses={200: {"model": PartnerResponse}},
        )
        self.router.add_api_route(
            "/partners/{partner_id}/keys",
            self.list_partner_keys,
            methods=["GET"],
            responses={200: {"model": list[KeyResponse]}},
        )
        self.router.add_api_route(
            "/partners/{partner_id}/policies",
            self.list_partner_policies,
            methods=["GET"],
            responses={200: {"model": list[PolicyResponse]}},
        )
        self.router.add_api_route(
            "/partners/{partner_id}/audit",
            self.partner_audit,
            methods=["GET"],
            responses={200: {"model": AuditEventListResponse}},
        )
        self.router.add_api_route(
            "/partners/{partner_id}/disable",
            self.disable_partner,
            methods=["POST"],
            responses={200: {"model": PartnerActionResponse}},
        )
        self.router.add_api_route(
            "/partners/{partner_id}/enable",
            self.enable_partner,
            methods=["POST"],
            responses={200: {"model": PartnerActionResponse}},
        )

    async def get_metadata(
        self,
        auth: Annotated[AuthCredentials, Depends(_admin_auth)],
    ) -> MetadataResponse:
        allowed = self.keys.allowed_algorithms
        return MetadataResponse(
            algorithms=[a.value for a in SigningAlgorithm if a.value in allowed],
            partner_statuses=[s.value for s in PartnerStatus],
            key_statuses=[s.value for s in KeyStatus],
            request_types=[t.value for t in RequestType],
            request_statuses=[s.value for s in RequestStatus],
            signing_algorithms=allowed_signing_algorithms(),
            fetch_types=[f.value for f in FetchType],
            policy_statuses=[s.value for s in PolicyStatus],
            identifier_pattern=IDENTIFIER_PATTERN,
            identifier_hint=IDENTIFIER_HINT,
        )

    async def get_catalogue(
        self,
        auth: Annotated[AuthCredentials, Depends(_admin_auth)],
    ) -> CatalogueResponse:
        """Choices for policy forms, from the configured catalogue sources.

        One entry per source: a registry's data scopes (``data_controller`` set)
        or an exchange's use cases. A source that cannot be read has ``error``
        set and no items (the form falls back to free text). Empty ``sources`` =
        none configured.
        """
        return CatalogueResponse(sources=await self.catalogue.catalogue())

    async def list_partners(
        self,
        auth: Annotated[AuthCredentials, Depends(_admin_auth)],
        status: Optional[PartnerStatus] = None,
    ) -> PartnerListResponse:
        rows = await self.partners.list_partners(status=status.value if status else None)
        return PartnerListResponse(
            count=len(rows),
            partners=[PartnerResponse.model_validate(p) for p in rows],
        )

    async def get_partner(
        self,
        partner_id: str,
        auth: Annotated[AuthCredentials, Depends(_admin_auth)],
    ) -> PartnerResponse:
        partner = await self.partners.get_partner(partner_id)
        if not partner:
            raise PartnerNotFoundError(partner_id)
        return PartnerResponse.model_validate(partner)

    async def list_partner_keys(
        self,
        partner_id: str,
        auth: Annotated[AuthCredentials, Depends(_admin_auth)],
    ) -> list[KeyResponse]:
        rows = await self.partners.list_keys(partner_id)
        return [KeyResponse.model_validate(k) for k in rows]

    async def list_partner_policies(
        self,
        partner_id: str,
        auth: Annotated[AuthCredentials, Depends(_admin_auth)],
        all_versions: bool = False,
    ) -> list[PolicyResponse]:
        rows = await self.policies.list_for_partner(partner_id, all_versions=all_versions)
        return [PolicyResponse.model_validate(p) for p in rows]

    async def partner_audit(
        self,
        partner_id: str,
        auth: Annotated[AuthCredentials, Depends(_admin_auth)],
    ) -> AuditEventListResponse:
        rows = await self.audit.list_for_partner(partner_id)
        return AuditEventListResponse(
            count=len(rows),
            events=[AuditEventResponse.model_validate(r) for r in rows],
        )

    async def disable_partner(
        self,
        partner_id: str,
        auth: Annotated[AuthCredentials, Depends(_admin_auth)],
    ) -> PartnerActionResponse:
        partner = await self.partners.set_status(
            partner_id, PartnerStatus.disabled, actor=PartnerManagerAuth.actor_info(auth)
        )
        return PartnerActionResponse(
            partner_id=partner.partner_id,
            status=partner.status,
            message="Partner disabled. Key-fetch now returns 'not available'.",
        )

    async def enable_partner(
        self,
        partner_id: str,
        auth: Annotated[AuthCredentials, Depends(_admin_auth)],
    ) -> PartnerActionResponse:
        partner = await self.partners.set_status(
            partner_id, PartnerStatus.active, actor=PartnerManagerAuth.actor_info(auth)
        )
        return PartnerActionResponse(
            partner_id=partner.partner_id,
            status=partner.status,
            message="Partner re-enabled. Active keys are served again.",
        )
