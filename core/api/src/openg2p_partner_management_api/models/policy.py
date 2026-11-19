from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModelWithId

# JSONB on PostgreSQL (production), plain JSON elsewhere (e.g. SQLite in tests).
_JSONList = JSON().with_variant(JSONB(), "postgresql")


class PolicyStatus(str, Enum):
    # pending: proposed by an open request, not served.
    # active: served by the policy-fetch API (one per policy key: partner + data
    #   controller, or partner + use case).
    # superseded: replaced by a newer approved version.
    # rejected: its request was rejected.
    # revoked: withdrawn by an approved policy request; nothing replaces it.
    pending = "pending"
    active = "active"
    superseded = "superseded"
    rejected = "rejected"
    revoked = "revoked"


class FetchType(str, Enum):
    oneshot = "oneshot"
    periodic = "periodic"


class PartnerPolicy(BaseModelWithId):
    """What a partner may access, versioned per policy key.

    Exactly one of ``data_controller`` / ``use_case`` is set: a scope policy for
    one registry (``allowed_data_scopes``), keyed by (partner, data_controller),
    or a use-case policy for one exchange use case (``name@major``), keyed by
    (partner, use_case). Changes are made only through partner requests:
    each request creates ``pending`` versions that approval turns ``active``
    (the previous active version becomes ``superseded``). Rows are never deleted.
    """

    __tablename__ = "pm_partner_policies"

    partner_id: Mapped[str] = mapped_column(String(255), index=True)
    # Registry's controller id (e.g. "farmer_registry"); set for a scope policy.
    data_controller: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    # Use case granted (name@major, e.g. "loan-profile@1"); set for a use-case policy.
    use_case: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(20), default=PolicyStatus.pending.value, index=True
    )

    allowed_data_scopes: Mapped[list] = mapped_column(_JSONList, default=list)
    allowed_purposes: Mapped[list] = mapped_column(_JSONList, default=list)
    allowed_subject_id_types: Mapped[list] = mapped_column(_JSONList, default=list)
    allowed_signing_algs: Mapped[list] = mapped_column(_JSONList, default=list)
    # ISO-8601 durations (e.g. P1Y); null = no limit.
    max_validity_duration: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    fetch_type: Mapped[str] = mapped_column(String(20), default=FetchType.oneshot.value)
    max_fetch_frequency: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    data_life: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # True = the partner may present consents it collected and signed itself
    # (the Consent Manager then accepts them; it cannot verify the subject agreed).
    allow_partner_consents: Mapped[bool] = mapped_column(Boolean, default=False)
    # True = the partner may collect consents by assisted confirmation in the
    # Consent Manager's partner portal: after the subject's national-ID login,
    # one 'I agree' tick instead of a signed form and a Consent Approver.
    allow_assisted_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)

    # The partner request that proposed this version.
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    # Approval time; null until approved.
    effective_from: Mapped[Optional[datetime]] = mapped_column(DateTime(), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
