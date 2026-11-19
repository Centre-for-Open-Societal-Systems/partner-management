"""Partner access policies: onboarding, policy requests, versioning, fetch API."""

import pytest

FARMER = "farmer_registry"
CROP = "crop_registry"
LOAN = "loan-profile@1"
NAME = "name-check@2"


def _scope_policy(controller=FARMER, scopes=("farmer.basic",), **extra):
    return {"data_controller": controller, "allowed_data_scopes": list(scopes), **extra}


def _use_case_policy(use_case=LOAN, **extra):
    return {"use_case": use_case, **extra}


def _onboard(client, keys, partner_id, policies):
    return client.post(
        "/partners/requests/onboarding",
        json={
            "partner_id": partner_id,
            "name": partner_id,
            "keys": [{"public_key": keys["ed"]}],
            "policies": policies,
        },
    )


def _policy_request(client, partner_id, policies=(), revoke=()):
    return client.post(
        "/partners/requests/policy",
        json={
            "partner_id": partner_id,
            "description": "change",
            "policies": list(policies),
            "revoke": [
                {"use_case": k} if "@" in k else {"data_controller": k} for k in revoke
            ],
        },
    )


def _approve(client, req_id):
    r = client.post(f"/partners/requests/{req_id}/approve", json={})
    assert r.status_code == 200, r.text
    return r.json()


def _code(r):
    return r.json()["errors"][0]["code"]


def _versions(client, partner_id):
    rows = client.get(f"/partners/{partner_id}/policies", params={"all_versions": "true"}).json()
    return {(p["data_controller"] or p["use_case"], p["version"]): p["status"] for p in rows}


@pytest.fixture(scope="module")
def bank(client, keys):
    """PARTNER_BANK_A, onboarded with a scope and a use-case policy, approved."""
    r = _onboard(
        client,
        keys,
        "PARTNER_BANK_A",
        [
            _scope_policy(
                scopes=[" farmer.basic ", "farmer.land", "farmer.basic", ""],
                allowed_purposes=["loan"],
                max_validity_duration="p1y",
            ),
            _use_case_policy(),
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["proposed_policies"]) == 2 and body["revoke"] == []
    # Pending until approved: not served.
    assert _versions(client, "PARTNER_BANK_A") == {(FARMER, 1): "pending", (LOAN, 1): "pending"}
    assert client.get("/policies/PARTNER_BANK_A").status_code == 404
    _approve(client, body["id"])
    return "PARTNER_BANK_A"


def test_onboarding_activates_policies(client, bank):
    assert _versions(client, bank) == {(FARMER, 1): "active", (LOAN, 1): "active"}
    r = client.get(f"/policies/{bank}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=60"
    body = r.json()
    assert body["partner_id"] == bank and len(body["policies"]) == 2
    farmer = next(p for p in body["policies"] if p["data_controller"] == FARMER)
    # Trimmed, blanks and duplicates dropped; durations upper-cased; defaults applied.
    assert farmer["allowed_data_scopes"] == ["farmer.basic", "farmer.land"]
    assert farmer["max_validity_duration"] == "P1Y"
    assert farmer["allowed_purposes"] == ["loan"]  # scope policies keep their purposes
    assert farmer["allowed_signing_algs"] == ["EdDSA", "ES256"]
    assert farmer["fetch_type"] == "oneshot"
    assert farmer["allow_partner_consents"] is False
    assert farmer["allow_assisted_confirmation"] is False
    assert farmer["version"] == 1 and farmer["effective_from"]
    # The version's id, as the staff API lists it.
    staff = client.get(f"/partners/{bank}/policies").json()
    assert farmer["id"] == next(p["id"] for p in staff if p["data_controller"] == FARMER)
    assert set(farmer) == {
        "id", "partner_id", "data_controller", "use_case", "version", "allowed_data_scopes",
        "allowed_purposes", "allowed_subject_id_types",
        "allowed_signing_algs", "max_validity_duration", "fetch_type",
        "max_fetch_frequency", "data_life", "allow_partner_consents",
        "allow_assisted_confirmation", "effective_from",
    }


def test_fetch_filters(client, bank):
    r = client.get(f"/policies/{bank}", params={"data_controller": FARMER})
    assert [p["data_controller"] for p in r.json()["policies"]] == [FARMER]
    r = client.get(f"/policies/{bank}", params={"use_case": LOAN})
    assert [(p["use_case"], p["data_controller"]) for p in r.json()["policies"]] == [(LOAN, None)]
    # Empty data_controller = the use-case policies.
    r = client.get(f"/policies/{bank}?data_controller=")
    assert [p["use_case"] for p in r.json()["policies"]] == [LOAN]
    # No filter = all active policies, registries first.
    r = client.get(f"/policies/{bank}")
    assert [p["data_controller"] or p["use_case"] for p in r.json()["policies"]] == [FARMER, LOAN]
    # No matching policy: the same fail-closed 404.
    for params in ({"data_controller": "land_registry"}, {"use_case": "other@1"}):
        r = client.get(f"/policies/{bank}", params=params)
        assert r.status_code == 404 and _code(r) == "PM-POLICY-404"


def test_fetch_fail_closed(client, bank):
    unknown = client.get("/policies/PARTNER_NOPE")
    assert unknown.status_code == 404 and _code(unknown) == "PM-POLICY-404"
    client.post(f"/partners/{bank}/disable")
    disabled = client.get(f"/policies/{bank}")
    assert disabled.status_code == 404 and _code(disabled) == "PM-POLICY-404"
    # Disabled partners take no policy changes.
    r = _policy_request(client, bank, [_scope_policy()])
    assert r.status_code == 400 and _code(r) == "PM-POLICY-400"
    client.post(f"/partners/{bank}/enable")
    assert client.get(f"/policies/{bank}").status_code == 200


def test_list_by_use_case(client, bank):
    r = client.get("/policies", params={"use_case": LOAN})
    assert r.status_code == 200 and "max-age=60" in r.headers["cache-control"]
    assert [(p["partner_id"], p["use_case"]) for p in r.json()["policies"]] == [(bank, LOAN)]
    assert r.json()["policies"][0]["id"] == (
        client.get(f"/policies/{bank}", params={"use_case": LOAN}).json()["policies"][0]["id"]
    )
    assert client.get("/policies", params={"use_case": "other@1"}).json()["count"] == 0
    r = client.get("/policies", params={"data_controller": FARMER})
    assert bank in {p["partner_id"] for p in r.json()["policies"]}
    r = client.get("/policies?data_controller=")
    assert {p["data_controller"] for p in r.json()["policies"]} == {None}
    # A filter is required.
    r = client.get("/policies")
    assert r.status_code == 400 and _code(r) == "PM-POLICY-400" and "filter" in r.text


def test_policy_request_versions_and_supersedes(client, bank):
    r = _policy_request(
        client,
        bank,
        [
            _scope_policy(
                scopes=["farmer.basic"],
                data_life="P30D",
                allow_partner_consents=True,
                allow_assisted_confirmation=True,
            )
        ],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["request_type"] == "policy" and body["proposed_policies"][0]["data_life"] == "P30D"
    assert body["proposed_policies"][0]["allow_partner_consents"] is True
    assert body["proposed_policies"][0]["allow_assisted_confirmation"] is True
    assert _versions(client, bank)[(FARMER, 2)] == "pending"
    # One pending change per (partner, data controller).
    clash = _policy_request(client, bank, [_scope_policy(scopes=["farmer.land"])])
    assert clash.status_code == 400 and _code(clash) == "PM-POLICY-409"
    clash = _policy_request(client, bank, revoke=[FARMER])
    assert _code(clash) == "PM-POLICY-409"
    # Still served: version 1 until approval.
    r = client.get(f"/policies/{bank}", params={"data_controller": FARMER})
    assert r.json()["policies"][0]["version"] == 1

    _approve(client, body["id"])
    versions = _versions(client, bank)
    assert versions[(FARMER, 1)] == "superseded" and versions[(FARMER, 2)] == "active"
    p = client.get(f"/policies/{bank}", params={"data_controller": FARMER}).json()["policies"][0]
    assert p["version"] == 2 and p["allowed_data_scopes"] == ["farmer.basic"]
    assert p["allow_partner_consents"] is True
    assert p["allow_assisted_confirmation"] is True
    # Staff default view: active only.
    active = client.get(f"/partners/{bank}/policies").json()
    farmer_active = next(a for a in active if a["data_controller"] == FARMER)
    assert farmer_active["allow_partner_consents"]
    assert farmer_active["allow_assisted_confirmation"]
    assert {(a["data_controller"] or a["use_case"], a["version"]) for a in active} == {
        (FARMER, 2), (LOAN, 1)
    }


def test_policy_request_reject(client, bank):
    r = _policy_request(client, bank, [_scope_policy(controller=CROP, scopes=["crop.sown"])])
    assert r.status_code == 200, r.text
    rj = client.post(f"/partners/requests/{r.json()['id']}/reject", json={"notes": "no"})
    assert rj.json()["status"] == "rejected"
    assert _versions(client, bank)[(CROP, 1)] == "rejected"
    assert client.get(f"/policies/{bank}", params={"data_controller": CROP}).status_code == 404
    # The next proposal takes the next version number.
    r = _policy_request(client, bank, [_scope_policy(controller=CROP, scopes=["crop.sown"])])
    _approve(client, r.json()["id"])
    assert _versions(client, bank)[(CROP, 2)] == "active"


def test_use_case_policies_independent(client, bank):
    """Each use case is its own policy: versioned, pending and revoked separately."""
    r = _policy_request(client, bank, [_use_case_policy(NAME, allowed_subject_id_types=["FIN"])])
    assert r.status_code == 200, r.text
    _approve(client, r.json()["id"])
    versions = _versions(client, bank)
    assert versions[(NAME, 1)] == "active" and versions[(LOAN, 1)] == "active"
    r = client.get(f"/policies/{bank}", params={"use_case": NAME})
    assert r.json()["policies"][0]["allowed_subject_id_types"] == ["FIN"]
    # A use-case policy lists no purposes: granting the use case grants its purpose.
    assert r.json()["policies"][0]["allowed_purposes"] == []

    loan_v1_id = client.get(f"/policies/{bank}", params={"use_case": LOAN}).json()["policies"][0]["id"]
    # A pending change to one use case blocks only that use case.
    loan = _policy_request(
        client,
        bank,
        [
            _use_case_policy(
                LOAN, data_life="P7D", allow_partner_consents=True,
                allow_assisted_confirmation=True,
            )
        ],
    )
    assert loan.status_code == 200, loan.text
    clash = _policy_request(client, bank, [_use_case_policy(LOAN)])
    assert clash.status_code == 400 and _code(clash) == "PM-POLICY-409"
    assert _code(_policy_request(client, bank, revoke=[LOAN])) == "PM-POLICY-409"
    name = _policy_request(client, bank, revoke=[NAME])
    assert name.status_code == 200, name.text
    assert name.json()["revoke"] == [{"use_case": NAME}]

    _approve(client, loan.json()["id"])
    _approve(client, name.json()["id"])
    versions = _versions(client, bank)
    assert versions[(LOAN, 1)] == "superseded" and versions[(LOAN, 2)] == "active"
    assert versions[(NAME, 1)] == "revoked"
    r = client.get(f"/policies/{bank}", params={"use_case": LOAN})
    assert r.json()["policies"][0]["data_life"] == "P7D"
    assert r.json()["policies"][0]["allow_partner_consents"] is True
    assert r.json()["policies"][0]["allow_assisted_confirmation"] is True
    assert r.json()["policies"][0]["id"] != loan_v1_id  # each version has its own id
    assert client.get(f"/policies/{bank}", params={"use_case": NAME}).status_code == 404
    assert client.get("/policies", params={"use_case": NAME}).json()["count"] == 0


def test_use_case_policy_takes_no_purposes(client, bank):
    """Refused on policy (update) requests as on onboarding; empty or blank is fine."""
    other = "other-check@1"
    r = _policy_request(client, bank, [_use_case_policy(other, allowed_purposes=["kyc"])])
    assert r.status_code == 400 and _code(r) == "G2P-REQ-102", r.text
    assert "allowed_purposes: not for a use-case policy ('other-check@1')" in r.text
    assert "granting a use case grants its purpose" in r.text
    blank = _policy_request(client, bank, [_use_case_policy(other, allowed_purposes=[" ", ""])])
    assert blank.status_code == 200, blank.text
    assert blank.json()["proposed_policies"][0]["allowed_purposes"] == []
    client.post(f"/partners/requests/{blank.json()['id']}/reject", json={})


def test_policy_revoke(client, bank):
    # Revoking needs an active policy, and not a change to the same key.
    for revoke in (["land_registry"], ["other@1"]):
        r = _policy_request(client, bank, revoke=revoke)
        assert r.status_code == 400 and _code(r) == "PM-POLICY-400"
    r = _policy_request(client, bank, [_scope_policy(controller=CROP)], revoke=[CROP])
    assert _code(r) == "PM-POLICY-400"
    assert _code(_policy_request(client, bank)) == "PM-POLICY-400"

    r = _policy_request(client, bank, revoke=[CROP, LOAN])
    assert r.status_code == 200, r.text
    assert r.json()["revoke"] == [{"data_controller": CROP}, {"use_case": LOAN}]
    _approve(client, r.json()["id"])
    versions = _versions(client, bank)
    assert versions[(CROP, 2)] == "revoked" and versions[(LOAN, 2)] == "revoked"
    assert client.get(f"/policies/{bank}?data_controller=").status_code == 404
    assert client.get("/policies", params={"use_case": LOAN}).json()["count"] == 0
    # A use case can be granted again afterwards (next version).
    r = _policy_request(client, bank, [_use_case_policy(LOAN)])
    _approve(client, r.json()["id"])
    assert _versions(client, bank)[(LOAN, 3)] == "active"


def test_revoke_entry_validation(client, bank):
    for revoke, message in [
        ([{"data_controller": FARMER, "use_case": LOAN}], "set one, not both"),
        ([{}], "set one"),
        ([{"use_case": LOAN}, {"use_case": LOAN}], "revoke: more than one entry"),
    ]:
        r = client.post(
            "/partners/requests/policy", json={"partner_id": bank, "revoke": revoke}
        )
        assert r.status_code == 400 and message in r.text, r.text


def test_policy_audit_trail(client, bank):
    actions = [e["action"] for e in client.get(f"/partners/{bank}/audit").json()["events"]]
    for expected in ["policy.requested", "policy.approved", "policy.rejected", "policy.revoked"]:
        assert expected in actions, expected


def test_onboarding_reject_rejects_policies(client, keys):
    r = _onboard(client, keys, "PARTNER_POL_REJ", [_use_case_policy()])
    client.post(f"/partners/requests/{r.json()['id']}/reject", json={})
    assert _versions(client, "PARTNER_POL_REJ") == {(LOAN, 1): "rejected"}


def test_policy_request_needs_approved_partner(client, keys):
    r = _onboard(client, keys, "PARTNER_POL_NEW", [])
    assert r.status_code == 200, r.text
    r = _policy_request(client, "PARTNER_POL_NEW", [_scope_policy()])
    assert r.status_code == 400 and _code(r) == "PM-POLICY-400" and "not approved" in r.text


def test_policy_request_unknown_partner(client):
    r = _policy_request(client, "PARTNER_GHOST", [_scope_policy()])
    assert r.status_code == 404 and _code(r) == "PM-PRT-404"


@pytest.mark.parametrize(
    "policy, message",
    [
        ({"data_controller": FARMER}, "allowed_data_scopes: required"),
        (_scope_policy(use_case=LOAN), "set one, not both"),
        ({"data_controller": "", "use_case": None}, "set one"),
        (_use_case_policy(allowed_data_scopes=["a"]), "allowed_data_scopes: only"),
        (_use_case_policy(allowed_purposes=["loan"]), "allowed_purposes: not for a use-case"),
        (_use_case_policy("loan-profile"), "name@major"),
        (_scope_policy(allowed_signing_algs=["HS256"]), "allowed_signing_algs: unsupported"),
        (_scope_policy(allowed_signing_algs=[" "]), "at least one algorithm"),
        (_scope_policy(fetch_type="daily"), "fetch_type"),
        (_scope_policy(max_validity_duration="1 year"), "ISO-8601"),
        (_scope_policy(data_life="P0D"), "longer than zero"),
        (_scope_policy(max_fetch_frequency="P" + "1" * 40 + "D"), "longer than 32"),
        (_scope_policy(controller="a/b"), ""),
    ],
)
def test_policy_validation(client, keys, policy, message):
    r = _onboard(client, keys, "PARTNER_POL_BAD", [policy])
    assert r.status_code == 400 and _code(r) == "G2P-REQ-102", r.text
    assert message in r.text


def test_one_policy_per_key_in_a_request(client, keys):
    r = _onboard(client, keys, "PARTNER_POL_DUP", [_use_case_policy(), _use_case_policy()])
    assert r.status_code == 400 and f"policies: more than one entry for use case {LOAN}" in r.text
    # Several use cases (and registries) in one request: one policy each.
    r = _onboard(
        client, keys, "PARTNER_POL_MIX",
        [_use_case_policy(), _use_case_policy(NAME), _scope_policy()],
    )
    assert r.status_code == 200, r.text
    assert _versions(client, "PARTNER_POL_MIX") == {
        (LOAN, 1): "pending", (NAME, 1): "pending", (FARMER, 1): "pending"
    }
