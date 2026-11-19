"""Catalogue sources: GET /catalogue and policy checks against them."""

import httpx
import pytest
from openg2p_partner_management_api.config import CatalogueSource, Settings
from openg2p_partner_management_api.services import CatalogueService

SCOPES_URL = "http://farmer-registry-partner-api/partner/data_scopes"
USE_CASES_URL = "http://agri-composite-api/composite/v1/use-cases"
FARMER = "farmer_registry"

SCOPES_BODY = {
    "data_controller": FARMER,
    "data_scopes": [
        {
            "scope_id": "farmer_registry.basic",
            "name": "basic",
            "data_controller": FARMER,
            "label": "Basic details",
            "description": "Name and village",
            "status": "ACTIVE",
            "current_version": 2,
            "versions": [
                {"version": 1, "fields": ["name"]},
                {"version": 2, "fields": ["name", "village"]},
            ],
        },
        {
            "scope_id": "farmer_registry.land",
            "name": "land",
            "data_controller": FARMER,
            "label": None,
            "description": None,
            "status": "ACTIVE",
            "current_version": 1,
            "versions": [{"version": 1, "fields": ["parcels"]}],
        },
        {
            "scope_id": "farmer_registry.old",
            "name": "old",
            "status": "RETIRED",
            "current_version": 1,
            "versions": [],
        },
    ],
}
USE_CASES_BODY = {
    "use_cases": [
        {
            "use_case": "loan-profile@1",
            "name": "loan-profile",
            "title": "Loan profile",
            "description": "Farmer profile for a crop loan",
            "purpose": "credit-assessment",
        }
    ]
}


class Upstream:
    """httpx.MockTransport handler: per-URL responses, counting calls."""

    def __init__(self):
        self.calls = {}
        self.down = set()
        self.status = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls[url] = self.calls.get(url, 0) + 1
        if url in self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if url in self.status:
            return httpx.Response(self.status[url], json={"error_message": "Unsigned GET is disabled"})
        body = SCOPES_BODY if url == SCOPES_URL else USE_CASES_BODY
        return httpx.Response(200, json=body)


@pytest.fixture
def upstream(client, monkeypatch):
    service = CatalogueService.get_component()
    up = Upstream()
    service.clear_cache()
    monkeypatch.setattr(service, "transport", httpx.MockTransport(up))
    monkeypatch.setattr(
        Settings.get_config(),
        "catalogue_sources",
        [
            CatalogueSource(kind="scopes", data_controller=FARMER, url=SCOPES_URL, label="Farmer Registry"),
            CatalogueSource(kind="use_cases", url=USE_CASES_URL, label="Agri Stack Composite"),
        ],
    )
    yield up
    service.clear_cache()


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


def _scope(*scopes, controller=FARMER):
    return {"data_controller": controller, "allowed_data_scopes": list(scopes)}


def _use_case(ref):
    return {"use_case": ref}


def test_catalogue_none_configured(client):
    assert client.get("/catalogue").json() == {"sources": []}


def test_catalogue_ok(client, upstream):
    r = client.get("/catalogue")
    assert r.status_code == 200, r.text
    scopes, use_cases = r.json()["sources"]
    assert scopes["kind"] == "scopes" and scopes["data_controller"] == FARMER
    assert scopes["label"] == "Farmer Registry" and scopes["error"] is None
    # Retired scopes are not offered; label falls back to the name; current fields.
    assert [(i["id"], i["label"], i["fields"]) for i in scopes["items"]] == [
        ("farmer_registry.basic", "Basic details", ["name", "village"]),
        ("farmer_registry.land", "land", ["parcels"]),
    ]
    assert use_cases["kind"] == "use_cases" and use_cases["data_controller"] is None
    assert use_cases["items"] == [
        {
            "id": "loan-profile@1",
            "label": "Loan profile",
            "description": "Farmer profile for a crop loan",
            "purpose": "credit-assessment",
            "fields": [],
        }
    ]


def test_catalogue_cached(client, upstream):
    client.get("/catalogue")
    client.get("/catalogue")
    assert upstream.calls == {SCOPES_URL: 1, USE_CASES_URL: 1}
    CatalogueService.get_component().clear_cache()
    client.get("/catalogue")
    assert upstream.calls[SCOPES_URL] == 2


def test_catalogue_source_errors_reported(client, upstream):
    upstream.down.add(USE_CASES_URL)
    upstream.status[SCOPES_URL] = 403
    r = client.get("/catalogue")
    assert r.status_code == 200
    scopes, use_cases = r.json()["sources"]
    assert scopes["items"] == [] and "403" in scopes["error"] and "unsigned read" in scopes["error"]
    assert use_cases["items"] == [] and "cannot reach" in use_cases["error"]
    # Errors are not cached: the next read retries.
    upstream.down.clear()
    upstream.status.clear()
    assert client.get("/catalogue").json()["sources"][1]["error"] is None


def test_catalogue_controller_mismatch(client, upstream, monkeypatch):
    monkeypatch.setattr(
        Settings.get_config(),
        "catalogue_sources",
        [CatalogueSource(kind="scopes", data_controller="crop_registry", url=SCOPES_URL)],
    )
    (src,) = client.get("/catalogue").json()["sources"]
    assert src["label"] == "crop_registry" and "farmer_registry" in src["error"]


def test_scopes_source_needs_controller():
    with pytest.raises(ValueError):
        CatalogueSource(kind="scopes", url=SCOPES_URL)


def test_known_names_accepted(client, keys, upstream):
    r = _onboard(
        client, keys, "PARTNER_CAT_OK",
        [_scope("farmer_registry.basic"), _use_case("loan-profile@1")],
    )
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == []


def test_unknown_scope_rejected(client, keys, upstream):
    r = _onboard(
        client, keys, "PARTNER_CAT_BAD_SCOPE",
        [_scope("farmer_registry.basic", "farmer_registry.old", "farmer_registry.nope")],
    )
    assert r.status_code == 400
    err = r.json()["errors"][0]
    assert err["code"] == "PM-POLICY-400"
    assert "farmer_registry.old" in err["message"] and "farmer_registry.nope" in err["message"]
    assert "farmer_registry.basic'" not in err["message"]
    # Nothing was created.
    assert client.get("/partners/PARTNER_CAT_BAD_SCOPE").status_code == 404


def test_unknown_use_case_rejected(client, keys, upstream):
    r = _onboard(client, keys, "PARTNER_CAT_BAD_UC", [_use_case("loan-profile@2")])
    assert r.status_code == 400
    assert "loan-profile@2" in r.json()["errors"][0]["message"]


def test_unconfigured_controller_not_checked(client, keys, upstream):
    r = _onboard(client, keys, "PARTNER_CAT_OTHER", [_scope("crop.any", controller="crop_registry")])
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == []
    assert upstream.calls == {}


def test_unreachable_source_accepts_with_warning(client, keys, upstream):
    upstream.down.add(SCOPES_URL)
    r = _onboard(client, keys, "PARTNER_CAT_DOWN", [_scope("farmer_registry.whatever")])
    assert r.status_code == 200, r.text
    (warning,) = r.json()["warnings"]
    assert "farmer_registry.whatever" in warning and "Farmer Registry" in warning
    # Kept on the request for the approver.
    req = client.get(f"/partners/requests/{r.json()['id']}").json()
    assert req["warnings"] == [warning]


def test_policy_request_checked(client, keys, upstream):
    r = _onboard(client, keys, "PARTNER_CAT_POLICY", [_scope("farmer_registry.basic")])
    assert r.status_code == 200, r.text
    assert client.post(f"/partners/requests/{r.json()['id']}/approve", json={}).status_code == 200
    body = {"partner_id": "PARTNER_CAT_POLICY", "policies": [_scope("farmer_registry.nope")]}
    r = client.post("/partners/requests/policy", json=body)
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "PM-POLICY-400"
    body["policies"] = [_scope("farmer_registry.land")]
    r = client.post("/partners/requests/policy", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == []


def test_no_sources_unchanged(client, keys):
    r = _onboard(client, keys, "PARTNER_CAT_NONE", [_scope("anything.goes"), _use_case("x@1")])
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == []


# --- Master Data code lists (purposes, subject ID types) ------------------------

MDS_URL = "http://commons-services-master-data-api"
MDS_VALUES_URL = f"{MDS_URL}/catalogue/get_list_values"
TOKEN_URL = "http://keycloak/realms/staff/protocol/openid-connect/token"
MDS_LISTS = {
    "CONSENT_PURPOSE": [
        {"value_code": "CREDIT_ASSESSMENT", "display": "Credit assessment", "status": "ACTIVE"},
        {"value_code": "SUBSIDY", "display": "Subsidy", "status": "ACTIVE"},
        {"value_code": "OLD_PURPOSE", "display": "Old", "status": "RETIRED"},
    ],
    "SUBJECT_ID_TYPE": [
        {"value_code": "FAYDA_FIN", "display": "Fayda FIN", "status": "ACTIVE"},
    ],
}


class MasterData:
    """Mock Keycloak token endpoint + MDS get_list_values."""

    def __init__(self):
        self.down = False
        self.missing = set()  # list codes not in the country's pack
        self.tokens = 0
        self.reads = []
        self.auth = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        import json

        url = str(request.url)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if url == TOKEN_URL:
            self.tokens += 1
            assert b"grant_type=client_credentials" in request.content
            assert b"client_id=pm-staff-portal" in request.content
            return httpx.Response(200, json={"access_token": "svc-token", "expires_in": 300})
        assert url == MDS_VALUES_URL, url
        self.auth.append(request.headers.get("authorization"))
        payload = json.loads(request.content)["request_body"]["request_payload"]
        code = payload["list_code"]
        self.reads.append(code)
        assert payload["version"] == "latest" and payload["include_retired"] is False
        if code in self.missing or code not in MDS_LISTS:
            return httpx.Response(
                200,
                json={
                    "response_header": {
                        "response_status": "ERROR",
                        "response_error_code": "G2P-CAT-404",
                        "response_error_message": f"List {code} not found",
                    },
                    "response_body": None,
                },
            )
        values = MDS_LISTS[code]
        return httpx.Response(
            200,
            json={
                "response_header": {"response_status": "SUCCESS"},
                "response_body": {
                    "response_payload": {
                        "list_code": code,
                        "version": {"version_no": 3},
                        "values": values,
                        "total": len(values),
                    }
                },
            },
        )


@pytest.fixture
def mds(client, monkeypatch):
    service = CatalogueService.get_component()
    md = MasterData()
    service.clear_cache()
    monkeypatch.setattr(service, "transport", httpx.MockTransport(md))
    cfg = Settings.get_config()
    monkeypatch.setattr(cfg, "mds_url", MDS_URL)
    monkeypatch.setattr(cfg, "mds_token_url", TOKEN_URL)
    monkeypatch.setattr(cfg, "mds_client_id", "pm-staff-portal")
    monkeypatch.setattr(cfg, "mds_client_secret", "secret")
    yield md
    service.clear_cache()


def _crop(controller="crop_registry"):
    """A scope policy for a registry with no catalogue source (scopes unchecked)."""
    return _scope("crop.any", controller=controller)


def _with(policy, **extra):
    return {**policy, **extra}


def test_mds_lists_in_catalogue(client, mds):
    purposes, id_types = client.get("/catalogue").json()["sources"]
    assert purposes["kind"] == "purposes" and purposes["error"] is None and purposes["note"] is None
    assert "CONSENT_PURPOSE v3" in purposes["label"]
    assert [(i["id"], i["label"]) for i in purposes["items"]] == [
        ("CREDIT_ASSESSMENT", "Credit assessment"),
        ("SUBSIDY", "Subsidy"),
    ]
    assert id_types["kind"] == "subject_id_types"
    assert [i["id"] for i in id_types["items"]] == ["FAYDA_FIN"]
    # Service-account token, fetched once and reused; lists cached.
    assert mds.auth == ["Bearer svc-token"] * 2 and mds.tokens == 1
    client.get("/catalogue")
    assert len(mds.reads) == 2


def test_mds_list_codes_configurable(client, mds, monkeypatch):
    monkeypatch.setattr(Settings.get_config(), "mds_subject_id_type_list_code", "")
    (purposes,) = client.get("/catalogue").json()["sources"]
    assert purposes["kind"] == "purposes"
    monkeypatch.setattr(Settings.get_config(), "mds_url", "")
    assert client.get("/catalogue").json()["sources"] == []


def test_mds_list_not_in_pack(client, keys, mds):
    mds.missing.add("SUBJECT_ID_TYPE")
    _, id_types = client.get("/catalogue").json()["sources"]
    assert id_types["items"] == [] and id_types["error"] is None
    assert "not in this country's Master Data" in id_types["note"]
    # Not checked, no warning.
    r = _onboard(
        client, keys, "PARTNER_MDS_NOLIST",
        [_with(_use_case("x@1"), allowed_subject_id_types=["ANY_ID"])],
    )
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == []


def test_mds_known_values_accepted(client, keys, mds):
    r = _onboard(
        client, keys, "PARTNER_MDS_OK",
        [_with(_crop(), allowed_purposes=["SUBSIDY"], allowed_subject_id_types=["FAYDA_FIN"])],
    )
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == []


def test_mds_unknown_values_rejected(client, keys, mds):
    r = _onboard(
        client, keys, "PARTNER_MDS_BAD",
        [
            _with(_crop(), allowed_purposes=["SUBSIDY", "OLD_PURPOSE", "MARKETING"]),
            _with(_crop("land_registry"), allowed_subject_id_types=["PASSPORT"]),
        ],
    )
    assert r.status_code == 400
    err = r.json()["errors"][0]
    assert err["code"] == "PM-POLICY-400"
    msg = err["message"]
    assert "OLD_PURPOSE" in msg and "MARKETING" in msg and "PASSPORT" in msg
    assert "'SUBSIDY'" not in msg and "CONSENT_PURPOSE" in msg
    assert client.get("/partners/PARTNER_MDS_BAD").status_code == 404


def test_mds_down_accepts_with_warning(client, keys, mds):
    mds.down = True
    sources = client.get("/catalogue").json()["sources"]
    assert all(s["items"] == [] and "cannot reach Master Data" in s["error"] for s in sources)
    r = _onboard(
        client, keys, "PARTNER_MDS_DOWN",
        [_with(_crop(), allowed_purposes=["ANYTHING"])],
    )
    assert r.status_code == 200, r.text
    (warning,) = r.json()["warnings"]
    assert "ANYTHING" in warning and "CONSENT_PURPOSE" in warning
    # Errors are not cached.
    mds.down = False
    assert client.get("/catalogue").json()["sources"][0]["error"] is None


def test_mds_token_refused_is_an_error(client, mds, monkeypatch):
    def refuse(request):
        return httpx.Response(401, json={"error": "unauthorized_client"})

    monkeypatch.setattr(CatalogueService.get_component(), "transport", httpx.MockTransport(refuse))
    purposes, _ = client.get("/catalogue").json()["sources"]
    assert "token request refused" in purposes["error"]


# --- Signing algorithms vs the partner's keys ------------------------------------


def test_signing_alg_warning_on_onboarding(client, keys):
    r = _onboard(
        client, keys, "PARTNER_ALG_ONB",
        [_with(_use_case("x@1"), allowed_signing_algs=["EdDSA", "RS256"])],
    )
    assert r.status_code == 200, r.text
    (warning,) = r.json()["warnings"]
    assert "['RS256']" in warning and "EdDSA" in warning
    # Matching algorithms (or the default, not chosen): no warning.
    r = _onboard(
        client, keys, "PARTNER_ALG_ONB2",
        [_with(_use_case("x@1"), allowed_signing_algs=["EdDSA"]), _scope("a.b")],
    )
    assert r.json()["warnings"] == []


def test_signing_alg_warning_on_policy_request(client, keys):
    r = _onboard(client, keys, "PARTNER_ALG_POL", [])
    assert client.post(f"/partners/requests/{r.json()['id']}/approve", json={}).status_code == 200
    body = {
        "partner_id": "PARTNER_ALG_POL",
        "policies": [_with(_scope("a.b"), allowed_signing_algs=["ES256"])],
    }
    r = client.post("/partners/requests/policy", json=body)
    assert r.status_code == 200, r.text
    (warning,) = r.json()["warnings"]
    assert "'a'" not in warning and "['ES256']" in warning and "active keys" in warning
