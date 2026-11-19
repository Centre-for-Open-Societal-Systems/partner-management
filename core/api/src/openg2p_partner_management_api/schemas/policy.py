import re
from datetime import datetime, timedelta
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from ..config import Settings
from ..models import IDENTIFIER_PATTERN, FetchType, SigningAlgorithm
from .key import blank_to_none

# Policy durations are stored in VARCHAR(32) columns.
_DURATION_MAX_LEN = 32
_DURATION_RE = re.compile(
    r"^P(?:(?P<years>\d+)Y)?(?:(?P<months>\d+)M)?(?:(?P<weeks>\d+)W)?"
    r"(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
# A use-case grant names one major version of a published use case: name@major.
USE_CASE_PATTERN = r"^[^\s/?#%@]+@\d+$"
DEFAULT_SIGNING_ALGS = ["EdDSA", "ES256"]


def allowed_signing_algorithms() -> List[str]:
    """Algorithms a policy may allow: PM's key algorithms narrowed by
    ``crypto_allowed_algorithms``. A policy can only narrow this set."""
    allowed = {a.strip() for a in Settings.get_config().crypto_allowed_algorithms}
    return [a.value for a in SigningAlgorithm if a.value in allowed]


def iso_duration_to_timedelta(duration: str) -> timedelta:
    """Parse a (subset of) ISO-8601 duration. Years ~ 365 days, months ~ 30 days."""
    match = _DURATION_RE.match(duration.strip())
    if not match:
        raise ValueError(f"Invalid ISO-8601 duration: {duration!r}")
    parts = {k: int(v) for k, v in match.groupdict().items() if v}
    return timedelta(
        days=parts.get("years", 0) * 365
        + parts.get("months", 0) * 30
        + parts.get("weeks", 0) * 7
        + parts.get("days", 0),
        hours=parts.get("hours", 0),
        minutes=parts.get("minutes", 0),
        seconds=parts.get("seconds", 0),
    )


def duration_problem(value: Optional[str]) -> Optional[str]:
    """Why ``value`` is not a usable policy duration, or None if it is (or unset)."""
    if value is None:
        return None
    if len(value) > _DURATION_MAX_LEN:
        return f"longer than {_DURATION_MAX_LEN} characters"
    try:
        delta = iso_duration_to_timedelta(value)
    except ValueError:
        return "not an ISO-8601 duration such as P30D, P1Y or PT12H"
    if delta.total_seconds() <= 0:
        return "must be longer than zero"
    return None


def _clean_list(values: List[str]) -> List[str]:
    """Trim entries, drop blanks and duplicates (keeps the given order)."""
    out: List[str] = []
    for v in values:
        v = v.strip()
        if v and v not in out:
            out.append(v)
    return out


def _blank_key(value):
    value = blank_to_none(value)
    return value.strip() or None if isinstance(value, str) else value


def _check_one_key(data_controller, use_case) -> None:
    if data_controller and use_case:
        raise ValueError("data_controller, use_case: set one, not both")
    if not data_controller and not use_case:
        raise ValueError(
            "data_controller, use_case: set one (a registry's scope policy or a use-case policy)"
        )


def policy_label(key: tuple) -> str:
    """'registry farmer_registry' / 'use case loan-profile@1' for a policy key."""
    kind, value = key
    return f"{'registry' if kind == 'data_controller' else 'use case'} {value}"


class PolicyRef(BaseModel):
    """Names one policy of a partner: ``{"data_controller": X}`` or ``{"use_case": Y}``."""

    data_controller: Optional[str] = Field(
        default=None, max_length=255, pattern=IDENTIFIER_PATTERN, examples=["farmer_registry"]
    )
    use_case: Optional[str] = Field(
        default=None, max_length=255, pattern=USE_CASE_PATTERN, examples=["loan-profile@1"]
    )

    _blank = field_validator("data_controller", "use_case", mode="before")(_blank_key)

    @model_validator(mode="after")
    def _one_key(self):
        _check_one_key(self.data_controller, self.use_case)
        return self

    @property
    def key(self) -> tuple:
        if self.data_controller:
            return ("data_controller", self.data_controller)
        return ("use_case", self.use_case)

    def as_dict(self) -> dict:
        kind, value = self.key
        return {kind: value}


class PolicyInput(BaseModel):
    """One policy proposed by an onboarding or policy request.

    Exactly one of:
    - ``data_controller`` (e.g. ``farmer_registry``): a scope policy for that
      registry — ``allowed_data_scopes`` required;
    - ``use_case`` (``name@major``, e.g. ``loan-profile@1``): a use-case policy
      for that exchange use case — ``allowed_data_scopes`` and
      ``allowed_purposes`` empty: granting a use case grants its purpose.
    Other fields:
    - purposes (scope policies only) / subject id types: empty = any; codes of
      the country's Master Data lists (CONSENT_PURPOSE, SUBJECT_ID_TYPE) when
      configured, else free.
    - ``allowed_signing_algs``: at least one of ``GET /metadata`` → ``signing_algorithms``;
      one that matches none of the partner's keys is accepted with a warning.
    - durations: ISO-8601 (``P30D``, ``P1Y``, ``PT12H``), > 0, or null.
    - ``allow_partner_consents``: true lets the partner present consents it
      collected and signed itself (default false).
    - ``allow_assisted_confirmation``: true lets the partner collect consents by
      assisted confirmation in the Consent Manager's partner portal: after the
      subject's national-ID login, one 'I agree' tick instead of a signed form
      and a Consent Approver (default false).
    Lists are trimmed, blanks and duplicates dropped.
    """

    model_config = ConfigDict(use_enum_values=True)

    data_controller: Optional[str] = Field(
        default=None, max_length=255, pattern=IDENTIFIER_PATTERN, examples=["farmer_registry"]
    )
    # Error messages name the field: the platform's error handler returns only
    # the message, not its location.
    use_case: Optional[str] = Field(default=None, max_length=255, examples=["loan-profile@1"])
    allowed_data_scopes: List[str] = Field(default_factory=list)
    allowed_purposes: List[str] = Field(default_factory=list)
    allowed_subject_id_types: List[str] = Field(default_factory=list)
    allowed_signing_algs: List[str] = Field(default_factory=lambda: list(DEFAULT_SIGNING_ALGS))
    max_validity_duration: Optional[str] = Field(default=None, examples=["P1Y"])
    fetch_type: FetchType = FetchType.oneshot
    max_fetch_frequency: Optional[str] = None
    data_life: Optional[str] = Field(default=None, examples=["P30D"])
    # True = the partner may present consents it collected and signed itself.
    allow_partner_consents: bool = False
    # True = the partner may collect consents by assisted confirmation (one
    # 'I agree' tick after the subject's national-ID login).
    allow_assisted_confirmation: bool = False

    _blank = field_validator("data_controller", "use_case", mode="before")(_blank_key)

    @field_validator(
        "allowed_data_scopes", "allowed_purposes",
        "allowed_subject_id_types", "allowed_signing_algs",
    )
    @classmethod
    def _clean(cls, values: List[str]) -> List[str]:
        return _clean_list(values)

    @field_validator("use_case")
    @classmethod
    def _use_case_ref(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not re.match(USE_CASE_PATTERN, value):
            raise ValueError(f"use_case: {value!r} must be 'name@major' (e.g. loan-profile@1)")
        return value

    @field_validator("allowed_signing_algs")
    @classmethod
    def _known_algs(cls, values: List[str]) -> List[str]:
        allowed = allowed_signing_algorithms()
        bad = [v for v in values if v not in allowed]
        if bad:
            raise ValueError(f"allowed_signing_algs: unsupported {bad}; allowed: {allowed}")
        if not values:
            raise ValueError("allowed_signing_algs: at least one algorithm is required")
        return values

    @field_validator("fetch_type", mode="before")
    @classmethod
    def _fetch_type(cls, value):
        types = [f.value for f in FetchType]
        if value not in types:
            raise ValueError(f"fetch_type: {value!r} is not one of {types}")
        return value

    @field_validator("max_validity_duration", "max_fetch_frequency", "data_life", mode="before")
    @classmethod
    def _duration(cls, value, info: ValidationInfo):
        if isinstance(value, str):
            value = value.strip().upper() or None
        problem = duration_problem(value)
        if problem:
            raise ValueError(f"{info.field_name}: {value!r} {problem}")
        return value

    @model_validator(mode="after")
    def _scope_or_use_case(self):
        _check_one_key(self.data_controller, self.use_case)
        if self.data_controller and not self.allowed_data_scopes:
            raise ValueError(
                f"allowed_data_scopes: required for data controller '{self.data_controller}'"
            )
        if self.use_case and self.allowed_data_scopes:
            raise ValueError(
                "allowed_data_scopes: only for a registry's policy (set data_controller)"
            )
        if self.use_case and self.allowed_purposes:
            raise ValueError(
                f"allowed_purposes: not for a use-case policy ('{self.use_case}'); granting "
                "a use case grants its purpose. Purposes belong in a registry's policy "
                "(set data_controller)"
            )
        return self

    @property
    def key(self) -> tuple:
        """The policy key: ("data_controller", X) or ("use_case", Y)."""
        if self.data_controller:
            return ("data_controller", self.data_controller)
        return ("use_case", self.use_case)


def check_distinct_keys(field: str, items: list) -> list:
    """At most one entry per policy key (data controller or use case) in ``field``."""
    seen, dup = set(), []
    for p in items:
        if p.key in seen and p.key not in dup:
            dup.append(p.key)
        seen.add(p.key)
    if dup:
        raise ValueError(
            f"{field}: more than one entry for {', '.join(policy_label(k) for k in dup)}"
        )
    return items


class PolicyOut(BaseModel):
    """A partner's active policy, as served to other modules by ``GET /policies``."""

    model_config = ConfigDict(from_attributes=True)

    # This policy version's id: consumers record it to say which version they applied.
    id: str
    partner_id: str
    data_controller: Optional[str] = None
    use_case: Optional[str] = None
    version: int
    allowed_data_scopes: List[str] = Field(default_factory=list)
    # Scope policies only; always empty for a use-case policy (its use case's
    # purpose is granted with it).
    allowed_purposes: List[str] = Field(default_factory=list)
    allowed_subject_id_types: List[str] = Field(default_factory=list)
    allowed_signing_algs: List[str] = Field(default_factory=list)
    max_validity_duration: Optional[str] = None
    fetch_type: str
    max_fetch_frequency: Optional[str] = None
    data_life: Optional[str] = None
    allow_partner_consents: bool = False
    allow_assisted_confirmation: bool = False
    effective_from: Optional[datetime] = None


class PartnerPoliciesOut(BaseModel):
    partner_id: str
    policies: List[PolicyOut]


class PolicyListOut(BaseModel):
    count: int
    policies: List[PolicyOut]


class PolicyResponse(PolicyOut):
    """Staff view of one policy version (any status)."""

    status: str  # pending | active | superseded | rejected | revoked
    request_id: str
    created_by: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: datetime
