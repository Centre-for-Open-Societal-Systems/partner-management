from typing import Literal, Optional

from openg2p_fastapi_common.config import Settings as BaseSettings
from pydantic import BaseModel, model_validator
from pydantic_settings import SettingsConfigDict

from . import __version__

_COMMON_AUTH_ENV = {
    "auth_enabled": "COMMON_AUTH_ENABLED",
    "auth_default_issuers": "COMMON_AUTH_DEFAULT_ISSUERS",
    "auth_default_audiences": "COMMON_AUTH_DEFAULT_AUDIENCES",
    "auth_default_jwks_urls": "COMMON_AUTH_DEFAULT_JWKS_URLS",
    "auth_default_id_token_verify_at_hash": "COMMON_AUTH_DEFAULT_ID_TOKEN_VERIFY_AT_HASH",
}


class CatalogueSource(BaseModel):
    """Where the staff UI's policy choices come from (see ``catalogue_sources``).

    - ``kind="scopes"``: a registry's data scope catalogue — unsigned
      ``GET {url}`` on its partner API (``/partner/data_scopes``), which needs the
      registry's unsigned-read switch on. ``data_controller`` is required: the
      policy key these scopes belong to.
    - ``kind="use_cases"``: an exchange's published use cases —
      ``GET {url}`` on e.g. the Composite's ``/composite/v1/use-cases``.
    """

    kind: Literal["scopes", "use_cases"]
    url: str
    label: Optional[str] = None
    data_controller: Optional[str] = None

    @model_validator(mode="after")
    def _controller_for_scopes(self):
        if self.data_controller is not None:
            self.data_controller = self.data_controller.strip() or None
        if self.kind == "scopes" and not self.data_controller:
            raise ValueError(f"catalogue source {self.url!r}: kind 'scopes' needs data_controller")
        if self.kind == "use_cases":
            self.data_controller = None
        return self


class BootstrapPartner(BaseModel):
    """A partner onboarded at install (see ``bootstrap_partners``)."""

    partner_id: str
    jwks_url: str
    name: Optional[str] = None
    org_name: Optional[str] = None
    description: Optional[str] = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="partner_manager_", env_file=".env", extra="allow"
    )

    openapi_title: str = "OpenG2P Partner Management API"
    openapi_description: str = """
    Central registry of OpenG2P partners, their public keys and their access
    policies (what each partner may ask for).

    All OpenG2P modules (g2p-bridge, consent-manager, ...) fetch partner
    public keys from this service instead of maintaining their own partner
    tables. Admin (staff-realm) APIs onboard partners and rotate keys through a
    simple created -> active -> disabled lifecycle. The key-fetch APIs are
    unauthenticated (they only return non-secret public material) and are
    exposed on the cluster-internal gateway.
    ***********************************
    Further details are in the GitBook: Platform Services > Partner Management.
    ***********************************
    """
    openapi_version: str = __version__

    db_dbname: str = "openg2p_partner_management_db"

    # --- Key material policy -------------------------------------------------
    # Signature algorithms accepted on input and advertised on the JWKS view.
    crypto_allowed_algorithms: list[str] = ["RS256", "ES256", "EdDSA"]
    # RSA keys weaker than this (bits) are rejected at onboarding.
    min_rsa_key_size: int = 2048
    # Timeout (seconds) when importing keys from a partner's jwks_url.
    jwks_fetch_timeout: int = 10
    # Partners with keys_from_jwks_url: how long keys read from the URL are
    # reused (s), and how long the last good answer is still served while the
    # URL fails (s); after that only the partner's stored keys are served.
    jwks_live_cache_ttl: int = 300
    jwks_live_stale_ttl: int = 21600
    jwks_live_fetch_timeout: float = 3.0

    # --- Partners onboarded at startup ----------------------------------------
    # Onboarded and approved by the staff API at startup (actor "bootstrap"),
    # with keys read from jwks_url when needed and no policy (each data
    # controller adds the partner's policies itself). A partner that already
    # exists is left as it is. JSON list of BootstrapPartner.
    bootstrap_partners: list[BootstrapPartner] = []

    # --- Public key-fetch API ------------------------------------------------
    # Cache-Control max-age (seconds) returned on key-fetch responses so callers
    # (e.g. the commons PartnerKeyStore) cache within a bounded rotation window.
    key_fetch_cache_max_age: int = 300
    # Cache-Control max-age (seconds) on policy-fetch responses. Shorter than keys:
    # a narrowed or revoked policy should reach callers (CM, Composite) quickly.
    policy_fetch_cache_max_age: int = 60

    # --- Catalogue sources (staff policy forms) -------------------------------
    # Where policy choices come from: registries' data scope catalogues and
    # exchanges' use cases (JSON list of CatalogueSource). With a source for a
    # data controller (or any use_cases source), the staff UI offers its items as
    # choices and requests naming anything else are rejected; an unreachable
    # source is skipped with a warning on the request. Empty = free text.
    catalogue_sources: list[CatalogueSource] = []
    # Per-source fetch timeout (seconds) and how long a fetched catalogue is reused.
    catalogue_fetch_timeout: float = 3.0
    catalogue_cache_ttl: int = 300

    # --- Master Data code lists (staff policy forms) ---------------------------
    # Purposes and subject ID types offered as choices, from the Master Data
    # Service's staff API (POST {mds_url}/catalogue/get_list_values), read with a
    # client-credentials token of PM's own Keycloak client (a service account, not
    # the user's token, so user data policies cannot narrow a shared cache). With
    # a list loaded, policies naming values outside it are rejected; MDS
    # unreachable = accepted with a warning; list not in the country's pack = no
    # check. Empty mds_url (or an empty list code) = free text.
    mds_url: str = ""
    mds_token_url: str = ""
    mds_client_id: str = ""
    mds_client_secret: str = ""
    mds_purpose_list_code: str = "CONSENT_PURPOSE"
    mds_subject_id_type_list_code: str = "SUBJECT_ID_TYPE"
    mds_cache_ttl: int = 300
    mds_timeout: float = 5.0

    # --- Admin auth (Keycloak staff realm) -----------------------------------
    # A caller must present a staff-realm JWT carrying this role (realm role or a
    # client role under auth_admin_client_id) to use the admin APIs. JWT issuer /
    # JWKS / audience are configured via COMMON_AUTH_* (Helm) or
    # PARTNER_MANAGER_AUTH_*. Set auth_admin_role="" to require only a valid token.
    auth_admin_role: str = "partner_manager"
    auth_admin_client_id: str = "partner-management"
    auth_enabled: bool = True
    auth_default_issuers: list[str] = []
    auth_default_audiences: list[str] = []
    auth_default_jwks_urls: list[str] = []
    auth_default_id_token_verify_at_hash: bool = True

    # --- Central Audit Manager (long-term forensic trail) --------------------
    # Off by default; emission requires audit_enabled=true AND a manager URL.
    # Delivery is fire-and-forget and never blocks or fails a request. This is
    # complementary to the local pm_audit_events ledger, which is always on.
    audit_enabled: bool = False
    audit_manager_url: str = ""
    audit_timeout_seconds: float = 2.0
    audit_source: str = "/openg2p/partner-management"
    audit_module: str = "partner-management"
    audit_anonymous_failures: bool = True

    @model_validator(mode="before")
    @classmethod
    def absorb_common_auth_env(cls, data):
        """Helm still sets COMMON_AUTH_*; honour those when partner_manager_ is unset."""
        import os

        if data is None:
            data = {}
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for field, env_name in _COMMON_AUTH_ENV.items():
            if field in out:
                continue
            value = os.getenv(env_name)
            if value is not None:
                out[field] = value
        return out
