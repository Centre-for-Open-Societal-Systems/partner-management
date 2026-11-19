from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..models import IDENTIFIER_PATTERN, SigningAlgorithm


def blank_to_none(value):
    """Treat "" / whitespace as "not supplied" (what older clients sent for auto)."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


class KeyInput(BaseModel):
    """A public key submitted for onboarding or rotation.

    Provide exactly one of ``public_key`` (PEM: SPKI or X.509 certificate) or
    ``jwk`` (a single JSON Web Key). ``kid`` and ``algorithm`` are optional: they
    are derived from the key when omitted (kid defaults to the key fingerprint).
    """

    public_key: Optional[str] = Field(
        default=None, description="PEM-encoded public key or X.509 certificate"
    )
    jwk: Optional[dict] = Field(default=None, description="A single public JWK")
    kid: Optional[str] = Field(default=None, max_length=255, pattern=IDENTIFIER_PATTERN)
    # Closed set (SigningAlgorithm); omit to infer from the key. The deployment's
    # crypto_allowed_algorithms may narrow it further (checked in KeyService).
    algorithm: Optional[SigningAlgorithm] = Field(default=None)
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None

    @field_validator("kid", "algorithm", mode="before")
    @classmethod
    def _blank_is_omitted(cls, value):
        return blank_to_none(value)

    @model_validator(mode="after")
    def _exactly_one_source(self):
        if bool(self.public_key) == bool(self.jwk):
            raise ValueError("Provide exactly one of 'public_key' or 'jwk'.")
        return self


class KeyResponse(BaseModel):
    """Admin view of a stored key (includes lifecycle + fingerprint).

    algorithm / status stay plain strings so legacy rows always load.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    partner_id: str
    kid: str
    algorithm: str
    public_key: str
    key_fingerprint: Optional[str] = None
    status: str
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    created_at: datetime


class PublicKeyResponse(BaseModel):
    """Unauthenticated fetch view: only what a verifier needs."""

    partner_id: str
    kid: str
    algorithm: str
    public_key: str
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None


class PublicKeyListResponse(BaseModel):
    partner_id: str
    keys: list[PublicKeyResponse]
