from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModelWithId

# JSONB on PostgreSQL (production), plain JSON elsewhere (e.g. SQLite in tests).
_JSONList = JSON().with_variant(JSONB(), "postgresql")


class RequestType(str, Enum):
    onboarding = "onboarding"
    key_update = "key_update"  # key rotation / addition / revocation
    policy = "policy"  # new policy versions / policy revocation


class RequestStatus(str, Enum):
    created = "created"
    approved = "approved"
    rejected = "rejected"


class PartnerRequest(BaseModelWithId):
    """An admin-facing workflow record for onboarding, key rotation or policy changes.

    The submitted key material is normalised (to canonical PEM) and validated at
    creation time and stashed in ``proposed_keys`` so approval is a cheap apply.
    In v1 the admin both files and approves; ``awe_request_id`` is reserved for a
    later Approval Workflow Engine integration (mirrors consent-manager).
    """

    __tablename__ = "pm_partner_requests"

    request_type: Mapped[str] = mapped_column(String(20), index=True)
    partner_id: Mapped[str] = mapped_column(String(255), index=True)

    # Snapshot of partner attributes proposed by an onboarding request.
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    org_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    jwks_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # Onboarding only: the partner's keys are read from jwks_url when needed.
    keys_from_jwks_url: Mapped[bool] = mapped_column(Boolean, default=False)

    # Normalised keys to activate on approval: list of
    # {kid, algorithm, public_key(PEM), key_fingerprint, not_before, not_after}.
    proposed_keys: Mapped[list] = mapped_column(_JSONList, default=list)
    # kids to revoke on approval (key rotation retirement).
    revoke_kids: Mapped[list] = mapped_column(_JSONList, default=list)
    # Policies proposed (PolicyInput dicts), also stored as pending
    # pm_partner_policies versions carrying this request's id.
    proposed_policies: Mapped[list] = mapped_column(_JSONList, default=list)
    # Policies revoked on approval, by key: [{"data_controller": X} | {"use_case": Y}].
    revoke: Mapped[list] = mapped_column("revoke_policies", _JSONList, default=list)
    # Checks that could not run at submission (e.g. a catalogue source was
    # unreachable), for the approver to verify by hand.
    warnings: Mapped[list] = mapped_column(_JSONList, default=list, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default=RequestStatus.created.value, index=True
    )
    submitted_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Reserved for future AWE integration (currently always null in v1).
    awe_request_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
