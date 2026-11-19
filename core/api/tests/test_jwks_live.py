"""Partners whose keys are read from their JWKS URL (keys_from_jwks_url), and bootstrap."""

import asyncio
import json

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from openg2p_partner_management_api import bootstrap
from openg2p_partner_management_api.config import BootstrapPartner
from openg2p_partner_management_api.services import KeyService

URL = "https://gateway.example.org/.well-known/jwks.json"


def _jwk(kid):
    jwk = json.loads(ECAlgorithm.to_jwk(ec.generate_private_key(ec.SECP256R1()).public_key()))
    return {**jwk, "kid": kid, "alg": "ES256", "use": "sig"}


@pytest.fixture
def jwks(monkeypatch):
    """The JWKS URL's answer: a mutable list of JWKs, or None for 'unreachable'."""
    state = {"keys": [], "calls": 0}
    ks = KeyService.get_component()
    ks._live.clear()

    class _Resp:
        def raise_for_status(self):
            if state["keys"] is None:
                raise RuntimeError("unreachable")

        def json(self):
            return {"keys": state["keys"]}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            state["calls"] += 1
            return _Resp()

    monkeypatch.setattr("openg2p_partner_management_api.services.key_service.httpx.AsyncClient", _Client)
    return state


def test_onboard_without_keys_needs_live_flag(client):
    r = client.post("/partners/requests/onboarding", json={"partner_id": "PARTNER_NOKEY", "name": "n"})
    assert r.status_code == 400
    r = client.post(
        "/partners/requests/onboarding",
        json={"partner_id": "PARTNER_NOKEY", "name": "n", "keys_from_jwks_url": True},
    )
    assert r.status_code in (400, 422)  # needs a jwks_url


def test_live_keys_served_and_cached(client, jwks):
    jwks["keys"] = [_jwk("gw-1")]
    r = client.post(
        "/partners/requests/onboarding",
        json={"partner_id": "PARTNER_GW", "name": "Gateway", "jwks_url": URL, "keys_from_jwks_url": True},
    )
    assert r.status_code == 200 and r.json()["keys_from_jwks_url"] is True
    assert r.json()["proposed_keys"] == []
    client.post(f"/partners/requests/{r.json()['id']}/approve", json={})
    assert client.get("/partners/PARTNER_GW").json()["keys_from_jwks_url"] is True

    fk = client.get("/keys/PARTNER_GW")
    assert fk.status_code == 200 and [k["kid"] for k in fk.json()["keys"]] == ["gw-1"]
    assert client.get("/keys/PARTNER_GW/gw-1").status_code == 200
    assert client.get("/keys/PARTNER_GW/jwks.json").json()["keys"][0]["kid"] == "gw-1"
    # Cached: the URL is not read again within the TTL.
    assert jwks["calls"] == 1

    # A rotated key at the URL shows once the cache is cleared (TTL elapsed).
    jwks["keys"] = [_jwk("gw-2")]
    KeyService.get_component()._live.clear()
    assert [k["kid"] for k in client.get("/keys/PARTNER_GW").json()["keys"]] == ["gw-2"]


def test_live_keys_stale_then_none(client, jwks):
    ks = KeyService.get_component()
    jwks["keys"] = [_jwk("gw-3")]
    assert client.get("/keys/PARTNER_GW").status_code == 200
    # The URL fails after the cache TTL: the last good keys are still served.
    jwks["keys"] = None
    fetched_at, keys = ks._live[URL]
    ks._live[URL] = (fetched_at - 10**4, keys)  # older than the soft TTL, within the stale TTL
    assert [k["kid"] for k in client.get("/keys/PARTNER_GW").json()["keys"]] == ["gw-3"]
    # Beyond the stale TTL: nothing, fail-closed.
    ks._live[URL] = (fetched_at - 10**6, keys)
    assert client.get("/keys/PARTNER_GW").status_code == 404


def test_live_keys_skip_refused_keys(client, jwks):
    jwks["keys"] = [{"kty": "EC", "crv": "P-384", "x": "AA", "y": "AA", "kid": "bad"}, _jwk("gw-4")]
    assert [k["kid"] for k in client.get("/keys/PARTNER_GW").json()["keys"]] == ["gw-4"]


def test_bootstrap_onboards_once(client, jwks, monkeypatch):
    jwks["keys"] = [_jwk("boot-1")]
    bp = BootstrapPartner(partner_id="PARTNER_BOOT", jwks_url=URL, name="Gateway")
    monkeypatch.setattr(bootstrap._config, "bootstrap_partners", [bp])

    asyncio.run(bootstrap.bootstrap_partners())
    p = client.get("/partners/PARTNER_BOOT").json()
    assert p["status"] == "active" and p["keys_from_jwks_url"] and p["approved_by"] == "bootstrap"
    assert client.get("/keys/PARTNER_BOOT").status_code == 200
    reqs = client.get("/partners/requests", params={"partner_id": "PARTNER_BOOT"}).json()

    # Rerun: nothing new.
    asyncio.run(bootstrap.bootstrap_partners())
    again = client.get("/partners/requests", params={"partner_id": "PARTNER_BOOT"}).json()
    assert again["count"] == reqs["count"] == 1
