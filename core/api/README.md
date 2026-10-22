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

## APIs

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/partners/requests/onboarding` | staff | File an onboarding request |
| POST | `/partners/requests/key-update` | staff | File a key rotation/update request |
| GET | `/partners/requests` | staff | List requests (filter by `status`, `partner_id`) |
| GET | `/partners/requests/{id}` | staff | Request detail |
| POST | `/partners/requests/{id}/approve` | staff | Approve (applies keys) |
| POST | `/partners/requests/{id}/reject` | staff | Reject |
| GET | `/partners` | staff | List partners |
| GET | `/partners/{partner_id}` | staff | Partner detail |
| GET | `/partners/{partner_id}/keys` | staff | All keys (any status) |
| POST | `/partners/{partner_id}/disable` | staff | Stop serving keys |
| POST | `/partners/{partner_id}/enable` | staff | Resume serving keys |
| GET | `/keys/{partner_id}` | **none** | Active public keys |
| GET | `/keys/{partner_id}/{kid}` | **none** | One active public key |
| GET | `/keys/{partner_id}/jwks.json` | **none** | JWKS view |
| GET | `/ping` | none | Health check |

Admin APIs require a Keycloak **staff-realm** JWT (forwarded by the IAM
staff-portal login) carrying the `partner_manager` role.

Key fetch first matches the exact registered partner ID. When no exact partner
exists, a DCI reference `PARTNER_<SENDER_ID>` can resolve to the existing sender
ID (uppercased, with hyphens replaced by underscores). For example,
`PARTNER_LIVE_STOCK_PARTNER_INTERNAL` resolves to `Live_stock_partner_internal`.
The fallback requires exactly one matching partner, including inactive partners
in the collision check. Ambiguous references return the same 404 as unavailable
keys. Exact IDs always take precedence, including disabled partners. Approval,
key validity, revocation, and `kid` checks apply unchanged; responses retain the
original registered identity. Admin IDs and stored partner/key records do not
change.

## Entrypoints

This one package builds two deployables that share the same models and database
(the national-social-registry pattern):

| Entrypoint | Serves | Auth |
| --- | --- | --- |
| `openg2p_partner_management_api.staff_portal_main:app` | admin endpoints (`/partners...`) | staff-realm JWT + `partner_manager` role |
| `openg2p_partner_management_api.partner_main:app` | key-fetch endpoints (`/keys...`) | none (public) |
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
