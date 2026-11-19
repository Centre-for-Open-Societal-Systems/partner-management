"""Partners onboarded at startup (``bootstrap_partners``).

Run by the staff API's ``migrate`` step, after the tables exist. Each partner
is onboarded with its keys read from its JWKS URL when needed and no policy,
and approved, both by the actor "bootstrap" (the install itself raises and
approves). Idempotent: a partner that already exists is left as it is, except
that its open onboarding request from an earlier bootstrap is approved.
"""

import logging

from .config import Settings
from .errors import PartnerExistsError
from .models import PartnerStatus, RequestStatus, RequestType
from .schemas import OnboardingRequestCreate
from .services import PartnerService, RequestService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)

BOOTSTRAP_ACTOR = {"name": "bootstrap"}


async def bootstrap_partners():
    if not _config.bootstrap_partners:
        return
    partners = PartnerService.get_component()
    requests = RequestService.get_component()
    for bp in _config.bootstrap_partners:
        try:
            await _bootstrap_one(partners, requests, bp)
        except Exception:
            # Never stop the service from starting; the partner can be onboarded by hand.
            _logger.exception("Bootstrap of partner '%s' failed", bp.partner_id)


async def _bootstrap_one(partners, requests, bp):
    existing = await partners.get_partner(bp.partner_id)
    if existing is None:
        try:
            req = await requests.create_onboarding(
                OnboardingRequestCreate(
                    partner_id=bp.partner_id,
                    name=bp.name or bp.partner_id,
                    org_name=bp.org_name,
                    description=bp.description or "Onboarded at install",
                    jwks_url=bp.jwks_url,
                    keys_from_jwks_url=True,
                ),
                actor=BOOTSTRAP_ACTOR,
            )
        except PartnerExistsError:
            # Another replica onboarded it meanwhile.
            _logger.info("Bootstrap partner '%s' already exists", bp.partner_id)
            return
        await requests.approve(req.id, actor=BOOTSTRAP_ACTOR, notes="Approved at install")
        _logger.info("Bootstrap partner '%s' onboarded (keys from %s)", bp.partner_id, bp.jwks_url)
        return

    if existing.status == PartnerStatus.created.value:
        open_reqs = await requests.list_requests(
            status=RequestStatus.created.value,
            partner_id=bp.partner_id,
            request_type=RequestType.onboarding.value,
        )
        for req in open_reqs:
            if req.submitted_by == BOOTSTRAP_ACTOR["name"]:
                await requests.approve(req.id, actor=BOOTSTRAP_ACTOR, notes="Approved at install")
                _logger.info("Bootstrap partner '%s' approved", bp.partner_id)
                return

    if not existing.keys_from_jwks_url or existing.jwks_url != bp.jwks_url:
        _logger.warning(
            "Partner '%s' exists with other key settings (keys_from_jwks_url=%s, jwks_url=%s); "
            "left as it is. Change it in Partner Management if needed.",
            bp.partner_id,
            existing.keys_from_jwks_url,
            existing.jwks_url,
        )
