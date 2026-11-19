from enum import Enum
from typing import Optional

from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModelWithId

# JSONB on PostgreSQL, plain JSON elsewhere (SQLite in tests).
_JSONObj = JSON().with_variant(JSONB(), "postgresql")


class AuditAction(str, Enum):
    partner_created = "partner.created"
    partner_approved = "partner.approved"
    partner_rejected = "partner.rejected"
    partner_disabled = "partner.disabled"
    partner_enabled = "partner.enabled"
    key_added = "key.added"
    key_revoked = "key.revoked"
    request_submitted = "request.submitted"
    request_approved = "request.approved"
    request_rejected = "request.rejected"
    policy_requested = "policy.requested"
    policy_approved = "policy.approved"
    policy_rejected = "policy.rejected"
    policy_revoked = "policy.revoked"


class AuditEvent(BaseModelWithId):
    """Append-only local ledger of material domain changes.

    Written in the SAME transaction as the change it records, so it is atomic
    with the change and can never be lost or drift — the authoritative
    "who changed what, when" record for a partner. Complements (does not replace)
    the central Audit Manager forensic trail. Rows are never updated or deleted.
    """

    __tablename__ = "pm_audit_events"

    # Staff identity behind the change (from the validated staff-realm JWT).
    actor_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    actor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    action: Mapped[str] = mapped_column(String(40), index=True)  # AuditAction value
    entity_type: Mapped[str] = mapped_column(String(32))  # partner | partner_key | partner_policy | partner_request
    entity_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Denormalised so a partner's whole history is one indexed query.
    partner_id: Mapped[str] = mapped_column(String(255), index=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Before -> after summary, e.g. {"from": "active", "to": "disabled"} or
    # {"kids_added": ["k2"], "kids_revoked": ["k1"]}.
    details: Mapped[dict] = mapped_column(_JSONObj, default=dict)
