from pydantic import BaseModel


class MetadataResponse(BaseModel):
    """Allowed values for every enum-backed field the staff UI offers as a select.

    Built from the model enums (and the crypto_allowed_algorithms config), so the
    UI and the API validators share one source of truth.
    """

    # Algorithms a key may declare on input in this deployment (omit = infer).
    algorithms: list[str]
    partner_statuses: list[str]
    key_statuses: list[str]
    request_types: list[str]
    request_statuses: list[str]
    # Policy form selects: algorithms a policy may allow, fetch types, statuses.
    signing_algorithms: list[str]
    fetch_types: list[str]
    policy_statuses: list[str]
    # Input rule for partner_id (onboarding) and kid, as a regex + human hint.
    identifier_pattern: str
    identifier_hint: str
