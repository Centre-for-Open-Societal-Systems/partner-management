"""Service-specific error codes and exceptions.

Reuses the openg2p-fastapi-common HTTP exception hierarchy so responses follow
the platform-standard {code, message} envelope.
"""

from openg2p_fastapi_common.errors.http_exceptions import (
    BadRequestError,
    NotFoundError,
)


class ErrorCodes:
    invalid_key = "PM-KEY-400"
    partner_exists = "PM-PRT-409"
    partner_not_found = "PM-PRT-404"
    request_not_found = "PM-REQ-404"
    request_not_open = "PM-REQ-409"
    jwks_fetch_failed = "PM-JWK-502"
    # Uniform fail-closed response for the public fetch API. Unknown and disabled
    # partners return the same code so callers cannot enumerate partner state.
    keys_not_available = "PM-KEY-404"
    invalid_policy = "PM-POLICY-400"
    policy_pending = "PM-POLICY-409"
    # Same fail-closed rule for the policy-fetch API.
    policies_not_available = "PM-POLICY-404"


class InvalidKeyError(BadRequestError):
    def __init__(self, message: str):
        super().__init__(code=ErrorCodes.invalid_key, message=message)


class PartnerExistsError(BadRequestError):
    def __init__(self, partner_id: str):
        super().__init__(
            code=ErrorCodes.partner_exists,
            message=f"Partner '{partner_id}' already exists.",
        )


class PartnerNotFoundError(NotFoundError):
    def __init__(self, partner_id: str):
        super().__init__(
            code=ErrorCodes.partner_not_found,
            message=f"Partner '{partner_id}' not found.",
        )


class RequestNotFoundError(NotFoundError):
    def __init__(self, request_id: str):
        super().__init__(
            code=ErrorCodes.request_not_found,
            message=f"Request '{request_id}' not found.",
        )


class RequestNotOpenError(BadRequestError):
    def __init__(self, message: str = "Request is not open for review."):
        super().__init__(code=ErrorCodes.request_not_open, message=message)


class JwksFetchError(BadRequestError):
    def __init__(self, message: str):
        super().__init__(code=ErrorCodes.jwks_fetch_failed, message=message)


class KeysNotAvailableError(NotFoundError):
    def __init__(self, partner_id: str):
        super().__init__(
            code=ErrorCodes.keys_not_available,
            message=f"No keys available for partner '{partner_id}'.",
        )


class InvalidPolicyError(BadRequestError):
    def __init__(self, message: str):
        super().__init__(code=ErrorCodes.invalid_policy, message=message)


class PolicyPendingError(BadRequestError):
    def __init__(self, message: str):
        super().__init__(code=ErrorCodes.policy_pending, message=message)


class PoliciesNotAvailableError(NotFoundError):
    def __init__(self, partner_id: str):
        super().__init__(
            code=ErrorCodes.policies_not_available,
            message=f"No policies available for partner '{partner_id}'.",
        )
