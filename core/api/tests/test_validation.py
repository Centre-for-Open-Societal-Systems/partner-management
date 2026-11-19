"""Server-side validation of the enum-backed fields the staff UI offers as selects.

Schema/query validation failures surface through the openg2p-fastapi-common
handler as 400 with code G2P-REQ-102; service-level key checks as PM-KEY-400.
"""

import asyncio

from openg2p_partner_management_api.models import PartnerKey, SigningAlgorithm
from openg2p_partner_management_api.services.request_service import _sm


def _onboard(client, keys, partner_id, **key_extra):
    return client.post(
        "/partners/requests/onboarding",
        json={
            "partner_id": partner_id,
            "name": partner_id,
            "keys": [{"public_key": keys["ec"], **key_extra}],
        },
    )


def _invalid(r):
    return r.status_code == 400 and r.json()["errors"][0]["code"] == "G2P-REQ-102"


def _onboard_active(client, keys, partner_id, kid):
    r = _onboard(client, keys, partner_id, kid=kid)
    assert r.status_code == 200, r.text
    client.post(f"/partners/requests/{r.json()['id']}/approve", json={})


def test_metadata_lists_allowed_values(client):
    m = client.get("/metadata")
    assert m.status_code == 200
    body = m.json()
    assert body["algorithms"] == ["RS256", "ES256", "EdDSA"]
    assert body["partner_statuses"] == ["created", "active", "disabled"]
    assert body["key_statuses"] == ["pending", "active", "revoked"]
    assert body["request_types"] == ["onboarding", "key_update", "policy"]
    assert body["request_statuses"] == ["created", "approved", "rejected"]
    assert body["signing_algorithms"] == ["RS256", "ES256", "EdDSA"]
    assert body["fetch_types"] == ["oneshot", "periodic"]
    assert body["policy_statuses"] == ["pending", "active", "superseded", "rejected", "revoked"]
    assert body["identifier_pattern"] and body["identifier_hint"]


def test_algorithm_must_be_a_supported_value(client, keys):
    r = _onboard(client, keys, "PARTNER_ALG_BAD", algorithm="HS256")
    assert _invalid(r) and "EdDSA" in r.text
    # Case matters: JWS names are exact.
    assert _invalid(_onboard(client, keys, "PARTNER_ALG_CASE", algorithm="es256"))


def test_algorithm_valid_and_blank_still_accepted(client, keys):
    ok = _onboard(client, keys, "PARTNER_ALG_OK", algorithm="ES256")
    assert ok.status_code == 200, ok.text
    assert ok.json()["proposed_keys"][0]["algorithm"] == "ES256"
    # Older clients sent "" for auto-detect: still means "infer from the key".
    blank = _onboard(client, keys, "PARTNER_ALG_BLANK", algorithm="", kid="")
    assert blank.status_code == 200, blank.text
    pk = blank.json()["proposed_keys"][0]
    assert pk["algorithm"] == "ES256" and pk["kid"].startswith("pm-")
    # A supported value that does not match the key is still rejected (PM-KEY-400).
    r = _onboard(client, keys, "PARTNER_ALG_MISMATCH", algorithm="RS256")
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "PM-KEY-400"


def test_partner_id_and_kid_format(client, keys):
    for bad in ["has space", "a/b", "q?x", "h#x", "p%2F"]:
        assert _invalid(_onboard(client, keys, bad)), bad
    assert _invalid(_onboard(client, keys, "PARTNER_KID", kid="bad/kid"))
    assert _onboard(client, keys, "PARTNER-ok.v1:x").status_code == 200


def test_jwks_url_must_be_http(client, keys):
    body = {"partner_id": "PARTNER_JWKS", "name": "J", "keys": [{"public_key": keys["ed"]}]}
    r = client.post("/partners/requests/onboarding", json={**body, "jwks_url": "ftp://x/jwks"})
    assert _invalid(r)
    r = client.post("/partners/requests/onboarding", json={**body, "jwks_url": ""})
    assert r.status_code == 200 and r.json()["jwks_url"] is None


def test_revoke_kids_must_be_current_keys(client, keys):
    _onboard_active(client, keys, "PARTNER_REV", "rev-1")
    base = {"partner_id": "PARTNER_REV", "keys": [{"public_key": keys["ed"], "kid": "rev-2"}]}
    bad = client.post("/partners/requests/key-update", json={**base, "revoke_kids": ["nope"]})
    assert bad.status_code == 400 and bad.json()["errors"][0]["code"] == "PM-KEY-400"
    assert "nope" in bad.text

    ok = client.post("/partners/requests/key-update", json={**base, "revoke_kids": ["rev-1"]})
    assert ok.status_code == 200, ok.text
    client.post(f"/partners/requests/{ok.json()['id']}/approve", json={})
    # Already revoked -> no longer revocable.
    again = client.post(
        "/partners/requests/key-update", json={"partner_id": "PARTNER_REV", "revoke_kids": ["rev-1"]}
    )
    assert again.status_code == 400


def test_list_filters_reject_unknown_values(client):
    assert _invalid(client.get("/partners", params={"status": "bogus"}))
    assert client.get("/partners", params={"status": "active"}).status_code == 200
    assert _invalid(client.get("/partners/requests", params={"status": "bogus"}))
    assert _invalid(client.get("/partners/requests", params={"request_type": "bogus"}))
    r = client.get("/partners/requests", params={"request_type": "key_update"})
    assert r.status_code == 200
    assert all(x["request_type"] == "key_update" for x in r.json()["requests"])


def test_legacy_rows_with_unknown_values_still_load(client):
    """Rows written before validation (e.g. an odd algorithm/status) must still render."""

    async def _insert():
        async with _sm()() as session:
            session.add(
                PartnerKey(
                    partner_id="PARTNER_LEGACY",
                    kid="legacy/kid",
                    algorithm="PS256",
                    public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----",
                    status="suspended",
                )
            )
            await session.commit()

    asyncio.run(_insert())
    r = client.get("/partners/PARTNER_LEGACY/keys")
    assert r.status_code == 200
    assert r.json()[0]["algorithm"] == "PS256" and r.json()[0]["status"] == "suspended"
    assert "PS256" not in {a.value for a in SigningAlgorithm}
