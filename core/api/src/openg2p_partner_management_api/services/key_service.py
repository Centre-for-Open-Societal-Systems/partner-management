import asyncio
import hashlib
import json
import logging
import time

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.x509 import load_pem_x509_certificate
from jwt.algorithms import ECAlgorithm, OKPAlgorithm, RSAAlgorithm
from openg2p_fastapi_common.service import BaseService

from ..config import Settings
from ..errors import InvalidKeyError, JwksFetchError

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)

# Default JWS algorithm per key type, when neither the JWK nor the caller says.
_DEFAULT_ALG_BY_KTY = {"OKP": "EdDSA", "EC": "ES256", "RSA": "RS256"}
# EC curve -> JWS algorithm (v1 supports P-256 / ES256 only).
_EC_CURVE_ALG = {"secp256r1": "ES256"}


class NormalizedKey:
    """A validated key reduced to canonical PEM + metadata."""

    def __init__(self, kid, algorithm, public_key_pem, key_fingerprint):
        self.kid = kid
        self.algorithm = algorithm
        self.public_key = public_key_pem
        self.key_fingerprint = key_fingerprint

    def as_dict(self, not_before=None, not_after=None) -> dict:
        return {
            "kid": self.kid,
            "algorithm": self.algorithm,
            "public_key": self.public_key,
            "key_fingerprint": self.key_fingerprint,
            "not_before": not_before.isoformat() if not_before else None,
            "not_after": not_after.isoformat() if not_after else None,
        }


class KeyService(BaseService):
    """Parses, validates and canonicalises partner public keys.

    Accepts PEM (SPKI or X.509 certificate) and JWK on input, always stores the
    canonical SubjectPublicKeyInfo PEM, and can render a stored key back to a
    JWKS document for the fetch API's ``/.well-known/jwks.json`` view.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Keys read from keys_from_jwks_url partners' URLs: url -> (fetched at, keys).
        self._live: dict = {}
        self._live_lock_map: dict = {}

    @property
    def allowed_algorithms(self) -> set:
        return {a.strip() for a in _config.crypto_allowed_algorithms if a.strip()}

    # --- public API ----------------------------------------------------------

    def normalize(
        self, public_key: str = None, jwk: dict = None, kid: str = None, algorithm: str = None
    ) -> NormalizedKey:
        """Validate one key and return its canonical form.

        Raises InvalidKeyError for anything we will not store (private keys,
        weak RSA, unsupported curve/type, disallowed algorithm, malformed PEM).
        """
        pub = self._load_public_key(public_key=public_key, jwk=jwk)
        inferred = self._infer_algorithm(pub)
        algorithm = (algorithm or inferred or "").strip()
        if not algorithm:
            raise InvalidKeyError("Could not determine the key algorithm.")
        if algorithm != inferred:
            raise InvalidKeyError(
                f"Declared algorithm '{algorithm}' does not match the key "
                f"(expected '{inferred}')."
            )
        if algorithm not in self.allowed_algorithms:
            raise InvalidKeyError(
                f"Algorithm '{algorithm}' is not allowed. "
                f"Allowed: {sorted(self.allowed_algorithms)}."
            )

        pem = pub.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        der = pub.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        fingerprint = hashlib.sha256(der).hexdigest()
        # Default the kid to a short, stable fingerprint so callers always have one.
        kid = (kid or "").strip() or f"pm-{fingerprint[:16]}"
        return NormalizedKey(kid, algorithm, pem, fingerprint)

    def to_jwks(self, keys: list[dict]) -> dict:
        """Render stored keys (dicts with public_key PEM, kid, algorithm) to JWKS."""
        out = []
        for k in keys:
            try:
                out.append(self._to_jwk(k["public_key"], k["kid"], k["algorithm"]))
            except Exception:
                _logger.exception("Skipping key '%s' in JWKS render", k.get("kid"))
        return {"keys": out}

    async def fetch_jwks_keys(self, jwks_url: str) -> list[dict]:
        """Fetch a partner's JWKS endpoint once and return KeyInput-shaped dicts.

        Each returned dict is {"jwk": <jwk>, "kid": <kid>} so it flows straight
        into normalize(). Import is one-shot: we store the result, we do not poll.
        """
        try:
            async with httpx.AsyncClient(timeout=_config.jwks_fetch_timeout) as client:
                resp = await client.get(jwks_url)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            raise JwksFetchError(f"Failed to fetch JWKS from '{jwks_url}': {e!r}") from e

        jwks = data.get("keys")
        if not isinstance(jwks, list) or not jwks:
            raise JwksFetchError(f"No keys found at JWKS endpoint '{jwks_url}'.")
        return [{"jwk": jwk, "kid": jwk.get("kid")} for jwk in jwks]

    async def live_keys(self, jwks_url: str) -> list[dict]:
        """A keys_from_jwks_url partner's keys, read from its JWKS URL (cached).

        Reused for jwks_live_cache_ttl; while the URL fails, the last good
        answer is served for up to jwks_live_stale_ttl, then nothing. Keys that
        would be refused at onboarding (weak, disallowed algorithm, private) are
        skipped. Returns dicts shaped like stored keys (kid, algorithm,
        public_key, not_before, not_after).
        """
        now = time.monotonic()
        cache = self._live
        hit = cache.get(jwks_url)
        if hit and now - hit[0] < _config.jwks_live_cache_ttl:
            return hit[1]

        lock = self._live_lock_map.setdefault(jwks_url, asyncio.Lock())
        async with lock:
            hit = cache.get(jwks_url)
            if hit and time.monotonic() - hit[0] < _config.jwks_live_cache_ttl:
                return hit[1]
            try:
                async with httpx.AsyncClient(timeout=_config.jwks_live_fetch_timeout) as client:
                    resp = await client.get(jwks_url)
                    resp.raise_for_status()
                    jwks = resp.json().get("keys")
                if not isinstance(jwks, list):
                    raise ValueError("no 'keys' list")
            except Exception as e:
                if hit and time.monotonic() - hit[0] < _config.jwks_live_stale_ttl:
                    _logger.warning("JWKS %s unavailable (%r); serving the last good keys", jwks_url, e)
                    return hit[1]
                _logger.warning("JWKS %s unavailable (%r); no keys from it", jwks_url, e)
                return []

            keys = []
            for jwk in jwks:
                try:
                    nk = self.normalize(jwk=jwk, kid=jwk.get("kid"), algorithm=jwk.get("alg"))
                except InvalidKeyError as e:
                    _logger.warning("Skipping key %r from %s: %s", jwk.get("kid"), jwks_url, e)
                    continue
                keys.append(
                    {
                        "kid": nk.kid,
                        "algorithm": nk.algorithm,
                        "public_key": nk.public_key,
                        "not_before": None,
                        "not_after": None,
                    }
                )
            cache[jwks_url] = (time.monotonic(), keys)
            return keys

    # --- internals -----------------------------------------------------------

    def _load_public_key(self, public_key: str = None, jwk: dict = None):
        if jwk:
            return self._public_key_from_jwk(jwk)

        text = (public_key or "").strip()
        if not text:
            raise InvalidKeyError("No key material provided.")
        if "PRIVATE KEY" in text:
            raise InvalidKeyError(
                "A private key was supplied. Provide the public key only."
            )
        try:
            if "BEGIN CERTIFICATE" in text:
                cert = load_pem_x509_certificate(text.encode("utf-8"))
                return cert.public_key()
            return serialization.load_pem_public_key(text.encode("utf-8"))
        except InvalidKeyError:
            raise
        except Exception as e:
            raise InvalidKeyError(f"Could not parse PEM public key: {e!r}") from e

    def _public_key_from_jwk(self, jwk: dict):
        kty = jwk.get("kty")
        raw = json.dumps(jwk)
        try:
            if kty == "EC":
                return ECAlgorithm.from_jwk(raw)
            if kty == "RSA":
                return RSAAlgorithm.from_jwk(raw)
            if kty == "OKP":
                return OKPAlgorithm.from_jwk(raw)
        except Exception as e:
            raise InvalidKeyError(f"Could not parse JWK: {e!r}") from e
        raise InvalidKeyError(f"Unsupported JWK key type: {kty!r}")

    def _infer_algorithm(self, pub) -> str:
        if isinstance(pub, rsa.RSAPublicKey):
            if pub.key_size < _config.min_rsa_key_size:
                raise InvalidKeyError(
                    f"RSA key too small: {pub.key_size} bits "
                    f"(minimum {_config.min_rsa_key_size})."
                )
            return "RS256"
        if isinstance(pub, ec.EllipticCurvePublicKey):
            alg = _EC_CURVE_ALG.get(pub.curve.name.lower())
            if not alg:
                raise InvalidKeyError(
                    f"Unsupported EC curve '{pub.curve.name}' (v1 supports P-256)."
                )
            return alg
        if isinstance(pub, ed25519.Ed25519PublicKey):
            return "EdDSA"
        raise InvalidKeyError("Unsupported public key type.")

    def _to_jwk(self, pem: str, kid: str, algorithm: str) -> dict:
        pub = serialization.load_pem_public_key(pem.encode("utf-8"))
        if isinstance(pub, rsa.RSAPublicKey):
            jwk = json.loads(RSAAlgorithm.to_jwk(pub))
        elif isinstance(pub, ec.EllipticCurvePublicKey):
            jwk = json.loads(ECAlgorithm.to_jwk(pub))
        elif isinstance(pub, ed25519.Ed25519PublicKey):
            jwk = json.loads(OKPAlgorithm.to_jwk(pub))
        else:
            raise ValueError("Unsupported key type for JWK render")
        jwk["kid"] = kid
        jwk["alg"] = algorithm
        jwk["use"] = "sig"
        return jwk
