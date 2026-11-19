from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..models import IDENTIFIER_PATTERN
from .key import KeyInput, blank_to_none
from .policy import PolicyInput, PolicyRef, check_distinct_keys


def _check_jwks_url(value):
    value = blank_to_none(value)
    if value is None:
        return None
    value = value.strip()
    if not value.lower().startswith(("https://", "http://")):
        raise ValueError("jwks_url must be an http(s) URL.")
    return value


class OnboardingRequestCreate(BaseModel):
    """Onboard a new partner and its initial public key(s)."""

    partner_id: str = Field(..., min_length=1, max_length=255, pattern=IDENTIFIER_PATTERN)
    name: str = Field(..., min_length=1, max_length=255)
    org_name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(
        default=None, description="Free-text description of the onboarding request"
    )
    jwks_url: Optional[str] = Field(default=None, max_length=1024)
    # Keys pasted directly. May be empty if import_from_jwks_url is set.
    keys: List[KeyInput] = Field(default_factory=list)
    # When true and jwks_url is set, keys are fetched from it and stored.
    import_from_jwks_url: bool = False
    # When true, the partner's keys are read from jwks_url whenever callers ask
    # for them (cached), instead of being copied once; no key is needed now, so
    # the partner can be onboarded before its JWKS URL answers.
    keys_from_jwks_url: bool = False
    # Optional access policies, activated (version 1) when the partner is approved.
    policies: List[PolicyInput] = Field(default_factory=list)

    _jwks_url = field_validator("jwks_url", mode="before")(_check_jwks_url)

    @model_validator(mode="after")
    def _jwks_url_for_live_keys(self):
        if self.keys_from_jwks_url and not self.jwks_url:
            raise ValueError("keys_from_jwks_url needs a jwks_url.")
        return self

    @field_validator("policies")
    @classmethod
    def _distinct_policies(cls, values):
        return check_distinct_keys("policies", values)


class KeyUpdateRequestCreate(BaseModel):
    """File a key rotation / update request for an existing partner."""

    partner_id: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(
        default=None, description="Why the keys are changing (e.g. scheduled rotation)"
    )
    keys: List[KeyInput] = Field(default_factory=list)
    jwks_url: Optional[str] = Field(default=None, max_length=1024)
    import_from_jwks_url: bool = False
    # kids of existing keys to revoke when this request is approved. Each must
    # be a current (non-revoked) key of the partner — checked in RequestService.
    revoke_kids: List[str] = Field(default_factory=list)

    _jwks_url = field_validator("jwks_url", mode="before")(_check_jwks_url)


class PolicyRequestCreate(BaseModel):
    """Change an existing partner's access policies.

    Each policy becomes a new active version of its key (data controller or use
    case) on approval, superseding the previous one; each entry of ``revoke``
    has its active policy revoked.
    """

    partner_id: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(
        default=None, description="Why the policy is changing"
    )
    policies: List[PolicyInput] = Field(default_factory=list)
    revoke: List[PolicyRef] = Field(
        default_factory=list,
        examples=[[{"data_controller": "farmer_registry"}, {"use_case": "loan-profile@1"}]],
    )

    @field_validator("policies")
    @classmethod
    def _distinct_policies(cls, values):
        return check_distinct_keys("policies", values)

    @field_validator("revoke")
    @classmethod
    def _distinct_revoke(cls, values):
        return check_distinct_keys("revoke", values)


class RequestReview(BaseModel):
    notes: Optional[str] = None


class ProposedKey(BaseModel):
    kid: str
    algorithm: str
    key_fingerprint: Optional[str] = None
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None


class PartnerRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_type: str  # onboarding | key_update | policy
    partner_id: str
    name: Optional[str] = None
    org_name: Optional[str] = None
    description: Optional[str] = None
    jwks_url: Optional[str] = None
    keys_from_jwks_url: bool = False
    proposed_keys: list = Field(default_factory=list)
    revoke_kids: list = Field(default_factory=list)
    proposed_policies: list = Field(default_factory=list)
    # Policies revoked on approval: [{"data_controller": X} | {"use_case": Y}].
    revoke: list = Field(default_factory=list)
    # Checks that could not run at submission (an unreachable catalogue source):
    # the approver should verify these by hand.
    warnings: list[str] = Field(default_factory=list)
    status: str  # created | approved | rejected
    submitted_by: Optional[str] = None
    reviewed_by: Optional[str] = None
    review_notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


    @field_validator("warnings", "revoke", mode="before")
    @classmethod
    def _null_list(cls, value):
        return value or []

    @field_validator("keys_from_jwks_url", mode="before")
    @classmethod
    def _null_false(cls, value):
        return bool(value)


class PartnerRequestListResponse(BaseModel):
    count: int
    requests: list[PartnerRequestResponse]
