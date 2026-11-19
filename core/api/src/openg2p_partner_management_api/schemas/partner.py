from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PartnerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    partner_id: str
    name: str
    org_name: Optional[str] = None
    description: Optional[str] = None
    jwks_url: Optional[str] = None
    # True: keys are read from jwks_url when needed (see GET /keys/{partner_id}).
    keys_from_jwks_url: bool = False
    status: str  # created | active | disabled
    created_by: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_validator("keys_from_jwks_url", mode="before")
    @classmethod
    def _null_false(cls, value):
        return bool(value)


class PartnerListResponse(BaseModel):
    count: int
    partners: list[PartnerResponse]


class PartnerActionResponse(BaseModel):
    """Returned by disable/enable and other partner state transitions."""

    partner_id: str
    status: str
    message: str = Field(default="")
