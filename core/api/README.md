# OpenG2P Partner Management API

Central registry of OpenG2P **partners** and their **public keys**. All OpenG2P
modules (g2p-bridge, consent-manager, …) fetch partner public keys from this
service instead of maintaining their own partner tables.

Built on [`openg2p-fastapi-common`](https://github.com/openg2p/openg2p-fastapi-common).

## What it does

- **Onboarding** — an admin registers a partner (`partner_id`, name, description)
  and its initial public key(s). Keys may be pasted (PEM / X.509 cert / JWK) or
  imported once from the partner's `jwks_url`.
- **Approval lifecycle** — a partner is `created` → (admin approves) `active` →
  `disabled`. Keys are only served for `active` partners.
- **Key rotation** — an `update` request adds new keys and/or revokes old ones.
  New and old keys can be active simultaneously for zero-downtime rotation.
- **Key fetch** — unauthenticated APIs return a partner's active public keys by
  `partner_id` (and optionally `kid`), plus a per-partner JWKS view. Fail-closed:
  unknown/disabled partners get a uniform `404 not available`.
- **Policies** — what a partner may access, one versioned policy per (partner,
  data controller) for a registry or per (partner, use case) for an exchange use case.
  Set at onboarding or by a `policy` request (new versions / revocations), applied
  on approval. Served fail-closed by `GET /policies/{partner_id}`.

## APIs

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/partners/requests/onboarding` | staff | File an onboarding request |
| POST | `/partners/requests/key-update` | staff | File a key rotation/update request |
| POST | `/partners/requests/policy` | staff | File a policy change/revocation request |
| GET | `/partners/requests` | staff | List requests (filter by `status`, `partner_id`) |
| GET | `/partners/requests/{id}` | staff | Request detail |
| POST | `/partners/requests/{id}/approve` | staff | Approve (applies keys) |
| POST | `/partners/requests/{id}/reject` | staff | Reject |
| GET | `/partners` | staff | List partners |
| GET | `/partners/{partner_id}` | staff | Partner detail |
| GET | `/partners/{partner_id}/keys` | staff | All keys (any status) |
| GET | `/partners/{partner_id}/policies` | staff | Active policies (`all_versions=true`: history) |
| POST | `/partners/{partner_id}/disable` | staff | Stop serving keys |
| POST | `/partners/{partner_id}/enable` | staff | Resume serving keys |
| GET | `/keys/{partner_id}` | **none** | Active public keys |
| GET | `/keys/{partner_id}/{kid}` | **none** | One active public key |
| GET | `/keys/{partner_id}/jwks.json` | **none** | JWKS view |
| GET | `/policies/{partner_id}` | **none** | Active policies: all, or `?data_controller=` / `?use_case=` |
| GET | `/policies` | **none** | Active policies of active partners; `?use_case=` and/or `?data_controller=` required |
| GET | `/ping` | none | Health check |

Admin APIs require a Keycloak **staff-realm** JWT (forwarded by the IAM
staff-portal login) carrying the `partner_manager` role.

## Entrypoints

This one package builds two deployables that share the same models and database
(the national-social-registry pattern):

| Entrypoint | Serves | Auth |
| --- | --- | --- |
| `openg2p_partner_management_api.staff_portal_main:app` | admin endpoints (`/partners...`) | staff-realm JWT + `partner_manager` role |
| `openg2p_partner_management_api.partner_main:app` | key- and policy-fetch endpoints (`/keys...`, `/policies...`) | none (public) |
| `openg2p_partner_management_api.main:app` | both (local dev / tests) | as above |

## Run locally

```bash
pip install -e .
cp .env.example .env          # then set COMMON_AUTH_ENABLED=false for no-Keycloak dev
# combined app (both APIs) for local dev:
python -m openg2p_partner_management_api.main migrate    # create tables
python -m openg2p_partner_management_api.main run        # start the server
# or run a single component, e.g. the staff-portal-api:
python -m openg2p_partner_management_api.staff_portal_main run
```

OpenAPI docs at `http://localhost:8000/docs`.
