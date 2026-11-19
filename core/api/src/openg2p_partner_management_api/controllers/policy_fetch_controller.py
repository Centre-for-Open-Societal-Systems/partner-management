import logging
from typing import Optional

from fastapi import Query, Response
from openg2p_fastapi_common.controller import BaseController

from ..config import Settings
from ..errors import InvalidPolicyError, PoliciesNotAvailableError
from ..schemas import PartnerPoliciesOut, PolicyListOut, PolicyOut
from ..services import PolicyService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)

_DATA_CONTROLLER = Query(
    None,
    description=(
        "Only this registry's policy (e.g. `farmer_registry`). "
        "Empty (`?data_controller=`) = use-case policies only."
    ),
)
_USE_CASE = Query(None, description="Only the policy for this use case (`name@major`).")


class PolicyFetchController(BaseController):
    """Unauthenticated policy-fetch APIs used by other OpenG2P modules.

    Same exposure and fail-closed rule as key fetch: the Consent Manager and the
    Composite read what a partner may ask for. An unknown partner, a non-active
    partner, or one with no matching active policy all return the same 404.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.policies = PolicyService.get_component()
        self.router.tags += ["Public: Policy Fetch"]

        self.router.add_api_route(
            "/policies",
            self.list_policies,
            methods=["GET"],
            responses={200: {"model": PolicyListOut}},
        )
        self.router.add_api_route(
            "/policies/{partner_id}",
            self.get_policies,
            methods=["GET"],
            responses={200: {"model": PartnerPoliciesOut}},
        )

    def _cache(self, response: Response):
        response.headers["Cache-Control"] = f"public, max-age={_config.policy_fetch_cache_max_age}"

    async def get_policies(
        self,
        partner_id: str,
        response: Response,
        data_controller: Optional[str] = _DATA_CONTROLLER,
        use_case: Optional[str] = _USE_CASE,
    ) -> PartnerPoliciesOut:
        """Active policies of an active partner; no filter = all of them."""
        rows = await self.policies.get_servable_policies(partner_id, data_controller, use_case)
        if not rows:
            raise PoliciesNotAvailableError(partner_id)
        self._cache(response)
        return PartnerPoliciesOut(
            partner_id=partner_id,
            policies=[PolicyOut.model_validate(r) for r in rows],
        )

    async def list_policies(
        self,
        response: Response,
        use_case: Optional[str] = _USE_CASE,
        data_controller: Optional[str] = _DATA_CONTROLLER,
    ) -> PolicyListOut:
        # A filter is required: no listing of every partner's policies.
        if not use_case and data_controller is None:
            raise InvalidPolicyError(
                "Give at least one filter: use_case, or data_controller "
                "(empty = use-case policies)."
            )
        rows = await self.policies.list_servable(use_case=use_case, data_controller=data_controller)
        self._cache(response)
        return PolicyListOut(
            count=len(rows),
            policies=[PolicyOut.model_validate(r) for r in rows],
        )
