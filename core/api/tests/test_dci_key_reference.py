"""DCI references reuse approved keys without creating a second partner."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _onboard(client, keys, partner_id, approve=True):
    response = client.post(
        "/partners/requests/onboarding",
        json={
            "partner_id": partner_id,
            "name": partner_id,
            "keys": [{"public_key": keys["rsa"], "kid": "original-key"}],
        },
    )
    assert response.status_code == 200
    if approve:
        response = client.post(
            f"/partners/requests/{response.json()['id']}/approve", json={}
        )
        assert response.status_code == 200


def _identity():
    sender = "Mixed-case_" + uuid.uuid4().hex
    return sender, "PARTNER_" + sender.replace("-", "_").upper()


def test_reference_serves_original_identity_in_all_key_views(client, keys):
    sender, reference = _identity()
    _onboard(client, keys, sender)
    exact = client.get(f"/keys/{sender}")
    alias = client.get(f"/keys/{reference}")
    assert exact.status_code == alias.status_code == 200
    assert alias.json()["keys"] == exact.json()["keys"]
    assert alias.json()["keys"][0]["partner_id"] == sender
    assert client.get(f"/keys/{reference}/original-key").status_code == 200
    assert client.get(f"/keys/{reference}/unknown-key").status_code == 404
    assert client.get(f"/keys/{reference}/jwks.json").json() == client.get(
        f"/keys/{sender}/jwks.json"
    ).json()
    # Key compatibility does not introduce an administrative partner alias.
    assert client.get(f"/partners/{reference}").status_code == 404


@pytest.mark.parametrize("state", ["created", "disabled", "revoked"])
def test_reference_keeps_lifecycle_checks(client, keys, state):
    sender, reference = _identity()
    _onboard(client, keys, sender, approve=state != "created")
    if state == "disabled":
        assert client.post(f"/partners/{sender}/disable").status_code == 200
    if state == "revoked":
        response = client.post(
            "/partners/requests/key-update",
            json={"partner_id": sender, "revoke_kids": ["original-key"]},
        )
        assert response.status_code == 200
        assert client.post(
            f"/partners/requests/{response.json()['id']}/approve", json={}
        ).status_code == 200
    assert client.get(f"/keys/{reference}").status_code == 404
    assert client.get(f"/keys/{reference}/original-key").status_code == 404
    assert client.get(f"/keys/{reference}/jwks.json").status_code == 404


@pytest.mark.parametrize("second_active", [True, False])
def test_colliding_normalizations_fail_closed_even_for_inactive_partner(
    client, keys, second_active
):
    sender, reference = _identity()
    other = sender.replace("-", "_")
    _onboard(client, keys, sender)
    _onboard(client, keys, other)
    if not second_active:
        assert client.post(f"/partners/{other}/disable").status_code == 200
    assert client.get(f"/keys/{reference}").status_code == 404
    assert client.get(f"/keys/{sender}").status_code == 200


def test_disabled_exact_identity_is_never_bypassed_by_fallback(client, keys):
    sender, reference = _identity()
    _onboard(client, keys, sender)
    _onboard(client, keys, reference)
    assert client.post(f"/partners/{reference}/disable").status_code == 200
    assert client.get(f"/keys/{reference}").status_code == 404
    assert client.get(f"/keys/{sender}").status_code == 200


def test_active_exact_identity_retains_its_own_keys(client, keys):
    sender, reference = _identity()
    _onboard(client, keys, sender)
    response = client.post(
        "/partners/requests/onboarding",
        json={
            "partner_id": reference,
            "name": reference,
            "keys": [{"public_key": keys["rsa2"], "kid": "exact-key"}],
        },
    )
    assert response.status_code == 200
    assert client.post(
        f"/partners/requests/{response.json()['id']}/approve", json={}
    ).status_code == 200
    result = client.get(f"/keys/{reference}")
    assert result.status_code == 200
    assert [k["kid"] for k in result.json()["keys"]] == ["exact-key"]
    assert client.get(f"/keys/{reference}/original-key").status_code == 404


@pytest.mark.parametrize("bound,days", [("not_after", -1), ("not_before", 1)])
def test_reference_does_not_serve_expired_or_future_keys(client, keys, bound, days):
    sender, reference = _identity()
    response = client.post(
        "/partners/requests/onboarding",
        json={
            "partner_id": sender,
            "name": sender,
            "keys": [{
                "public_key": keys["rsa"],
                "kid": "time-limited-key",
                bound: (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
            }],
        },
    )
    assert response.status_code == 200
    assert client.post(
        f"/partners/requests/{response.json()['id']}/approve", json={}
    ).status_code == 200
    assert client.get(f"/keys/{reference}").status_code == 404
    assert client.get(f"/keys/{reference}/time-limited-key").status_code == 404
    assert client.get(f"/keys/{reference}/jwks.json").status_code == 404
