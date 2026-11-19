"""Catalogue sources: the choices a policy may name, read from their owners.

A registry publishes its data scopes (``GET /partner/data_scopes``), an exchange
its use cases (``GET /composite/v1/use-cases``). Partner Management reads them
server-to-server (unsigned GETs, it has no signing key), caches each source for
``catalogue_cache_ttl`` seconds, and:

- serves them to the staff UI (``GET /catalogue``) so policy forms offer choices;
- checks proposed policies against them. A scope policy is checked only when a
  source exists for its data controller; a use-case policy when any use_cases
  source exists. An unreachable source does not block a request (approval is a
  human check): the request is accepted and carries a warning.

Purposes and subject ID types come from the Master Data Service's code lists
(``mds_purpose_list_code``, ``mds_subject_id_type_list_code``), read with a
client-credentials token of PM's own Keycloak client — never the user's token:
MDS applies the caller's data policies, which must not narrow a shared cache. A
loaded list is enforced; MDS unreachable = accepted with a warning; a list not
in the country's pack (``G2P-CAT-404``) = not checked, a note in the catalogue.
Nothing here is used at run time (key / policy fetch).
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import httpx
from openg2p_fastapi_common.service import BaseService

from ..config import CatalogueSource, Settings
from ..errors import InvalidPolicyError
from ..schemas.catalogue import CatalogueItem, CatalogueSourceOut

_logger = logging.getLogger(Settings.get_config().logging_default_logger_name)

_RETIRED = "RETIRED"

# Master Data lists: (kind, settings attribute of its list code, label, policy field).
_MDS_LISTS = (
    ("purposes", "mds_purpose_list_code", "Purposes", "allowed_purposes"),
    ("subject_id_types", "mds_subject_id_type_list_code", "Subject ID types",
     "allowed_subject_id_types"),
)


def _sources() -> list[CatalogueSource]:
    return list(Settings.get_config().catalogue_sources or [])


def _mds_lists() -> list[tuple[str, str, str, str]]:
    """Configured Master Data lists: (kind, list_code, label, policy field)."""
    cfg = Settings.get_config()
    if not (cfg.mds_url or "").strip():
        return []
    out = []
    for kind, attr, label, field in _MDS_LISTS:
        code = (getattr(cfg, attr) or "").strip()
        if code:
            out.append((kind, code, label, field))
    return out


def _source_label(source: CatalogueSource) -> str:
    return source.label or source.data_controller or source.url


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        msg = body.get("error_message") or (body.get("error") or {}).get("message")
        if not msg and body.get("errors"):
            msg = (body["errors"][0] or {}).get("message")
        if msg:
            return str(msg)
    return str(body)[:200]


def _scope_items(source: CatalogueSource, body: dict) -> list[CatalogueItem]:
    if body.get("error_code"):
        raise ValueError(f"{body.get('error_code')}: {body.get('error_message') or ''}".strip())
    reported = body.get("data_controller")
    if reported and reported != source.data_controller:
        raise ValueError(
            f"the registry's data controller is '{reported}', not '{source.data_controller}' "
            "as configured"
        )
    items = []
    for scope in body.get("data_scopes") or []:
        if str(scope.get("status") or "").upper() == _RETIRED:
            continue  # no longer offered
        current = scope.get("current_version")
        version = next(
            (v for v in scope.get("versions") or [] if v.get("version") == current), None
        )
        items.append(
            CatalogueItem(
                id=scope["scope_id"],
                label=scope.get("label") or scope.get("name"),
                description=scope.get("description"),
                fields=list((version or {}).get("fields") or []),
            )
        )
    return items


def _use_case_items(body: dict) -> list[CatalogueItem]:
    return [
        CatalogueItem(
            id=uc["use_case"],
            label=uc.get("title") or uc.get("name"),
            description=uc.get("description"),
            purpose=uc.get("purpose"),
        )
        for uc in body.get("use_cases") or []
    ]


class CatalogueService(BaseService):
    """Fetches, caches (per source, single-flight) and checks catalogue sources."""

    def __init__(self, name: str = ""):
        super().__init__(name)
        # (kind, url) -> (expires_at, CatalogueSourceOut); only successful reads.
        self._cache: dict[tuple, tuple[float, CatalogueSourceOut]] = {}
        self._inflight: dict[tuple, asyncio.Task] = {}
        # Tests swap in an httpx.MockTransport.
        self.transport: Optional[httpx.AsyncBaseTransport] = None
        # Master Data token (client credentials), reused until shortly before expiry.
        self._mds_token: Optional[str] = None
        self._mds_token_expires_at = 0.0

    def clear_cache(self) -> None:
        self._cache.clear()
        self._mds_token = None

    # --- fetching ------------------------------------------------------------

    async def catalogue(self) -> list[CatalogueSourceOut]:
        """Every configured source, read concurrently; errors reported per source."""
        reads = [self.read(s) for s in _sources()]
        reads += [self.read_mds(kind, code, label) for kind, code, label, _ in _mds_lists()]
        return list(await asyncio.gather(*reads))

    async def _cached(
        self, key: tuple, fetch: Callable[[], Awaitable[CatalogueSourceOut]], ttl: float
    ) -> CatalogueSourceOut:
        """Cached (successful reads only) and single-flight per key."""
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        task = self._inflight.get(key)
        if task is None or task.get_loop() is not asyncio.get_running_loop():
            task = asyncio.ensure_future(fetch())
            self._inflight[key] = task
        try:
            out = await task
        finally:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)
        if out.error is None:
            self._cache[key] = (time.monotonic() + ttl, out)
        return out

    async def read(self, source: CatalogueSource) -> CatalogueSourceOut:
        return await self._cached(
            (source.kind, source.url, source.data_controller),
            lambda: self._fetch(source),
            Settings.get_config().catalogue_cache_ttl,
        )

    async def read_mds(self, kind: str, list_code: str, label: str) -> CatalogueSourceOut:
        cfg = Settings.get_config()
        return await self._cached(
            ("mds", kind, cfg.mds_url, list_code),
            lambda: self._fetch_mds(kind, list_code, label),
            cfg.mds_cache_ttl,
        )

    async def _fetch(self, source: CatalogueSource) -> CatalogueSourceOut:
        out = CatalogueSourceOut(
            kind=source.kind, data_controller=source.data_controller, label=_source_label(source)
        )
        try:
            async with httpx.AsyncClient(
                timeout=Settings.get_config().catalogue_fetch_timeout, transport=self.transport
            ) as client:
                resp = await client.get(source.url)
            if resp.status_code == 403 and source.kind == "scopes":
                raise ValueError(
                    f"HTTP 403 ({_error_detail(resp)}); turn on the registry's unsigned read "
                    "of its data scope catalogue"
                )
            if resp.status_code >= 400:
                raise ValueError(f"HTTP {resp.status_code} ({_error_detail(resp)})")
            body = resp.json()
            if not isinstance(body, dict):
                raise ValueError("unexpected response (not a JSON object)")
            out.items = (
                _scope_items(source, body) if source.kind == "scopes" else _use_case_items(body)
            )
        except httpx.HTTPError as e:
            out.error = f"cannot reach {source.url}: {e.__class__.__name__} {e}".strip()
        except Exception as e:  # noqa: BLE001 - reported per source, never raised
            out.error = f"cannot read {source.url}: {e}"
        if out.error:
            _logger.warning("Catalogue source %s: %s", out.label, out.error)
        return out

    async def _mds_access_token(self, client: httpx.AsyncClient) -> Optional[str]:
        """Client-credentials token of PM's own client; None when no token URL is set."""
        cfg = Settings.get_config()
        if not cfg.mds_token_url:
            return None
        if self._mds_token and time.monotonic() < self._mds_token_expires_at:
            return self._mds_token
        resp = await client.post(
            cfg.mds_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": cfg.mds_client_id,
                "client_secret": cfg.mds_client_secret,
            },
        )
        if resp.status_code >= 400:
            raise ValueError(f"token request refused (HTTP {resp.status_code}): {resp.text[:200]}")
        body = resp.json() or {}
        token = body.get("access_token")
        if not token:
            raise ValueError("token response has no access_token")
        try:
            lifetime = float(body.get("expires_in") or 300)
        except (TypeError, ValueError):
            lifetime = 300.0
        self._mds_token = token
        self._mds_token_expires_at = time.monotonic() + max(lifetime - min(30.0, lifetime / 10), 1.0)
        return token

    async def _fetch_mds(self, kind: str, list_code: str, label: str) -> CatalogueSourceOut:
        cfg = Settings.get_config()
        out = CatalogueSourceOut(kind=kind, label=f"{label} (Master Data {list_code})")
        url = cfg.mds_url.rstrip("/") + "/catalogue/get_list_values"
        envelope = {
            "request_header": {
                "sender_app_mnemonic": "partner-management",
                "sender_app_url": "",
                "request_id": str(uuid.uuid4()),
                "request_timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            },
            "request_body": {
                "request_payload": {
                    "list_code": list_code,
                    "version": "latest",
                    "include_retired": False,
                }
            },
        }
        try:
            async with httpx.AsyncClient(timeout=cfg.mds_timeout, transport=self.transport) as client:
                for attempt in (1, 2):
                    token = await self._mds_access_token(client)
                    headers = {"Authorization": f"Bearer {token}"} if token else {}
                    resp = await client.post(url, json=envelope, headers=headers)
                    if resp.status_code == 401 and attempt == 1 and token:
                        self._mds_token = None  # expired or revoked early: once more
                        continue
                    break
            if resp.status_code >= 400:
                raise ValueError(f"HTTP {resp.status_code} ({_error_detail(resp)})")
            body = resp.json()
            if not isinstance(body, dict):
                raise ValueError("unexpected response (not a JSON object)")
            header = body.get("response_header") or {}
            if str(header.get("response_status") or "").upper() == "ERROR":
                code = header.get("response_error_code") or "ERROR"
                if str(code).endswith("-404"):
                    out.note = f"{list_code} is not in this country's Master Data: free text."
                    return out
                raise ValueError(f"{code} {header.get('response_error_message') or ''}".strip())
            payload = (body.get("response_body") or {}).get("response_payload") or {}
            version = (payload.get("version") or {}).get("version_no")
            if version is not None:
                out.label = f"{label} (Master Data {list_code} v{version})"
            out.items = [
                CatalogueItem(id=v["value_code"], label=v.get("display") or v["value_code"])
                for v in payload.get("values") or []
                if str(v.get("status") or "").upper() != _RETIRED
            ]
            if not out.items:
                out.note = f"{list_code} has no values: free text."
        except httpx.HTTPError as e:
            out.error = f"cannot reach Master Data: {e.__class__.__name__} {e}".strip()
        except Exception as e:  # noqa: BLE001 - reported per list, never raised
            out.error = f"cannot read Master Data list {list_code}: {e}"
        if out.error:
            _logger.warning("Master Data list %s: %s", list_code, out.error)
        return out

    # --- checking proposals --------------------------------------------------

    async def check_policies(self, policies: list) -> list[str]:
        """Reject names a reachable source does not list; return warnings.

        Raises InvalidPolicyError (PM-POLICY-400) naming unknown scopes, use
        cases, purposes or subject ID types. A policy with no configured source
        is not checked, nor is a Master Data list the country does not have. When
        a relevant source cannot be read, unknown names are accepted with a warning.
        """
        if not policies:
            return []
        sources = _sources()
        problems, warnings = [], []
        for p in policies:
            if p.data_controller:
                relevant = [
                    s for s in sources
                    if s.kind == "scopes" and s.data_controller == p.data_controller
                ]
                names, what = p.allowed_data_scopes, f"scopes for '{p.data_controller}'"
            else:
                relevant = [s for s in sources if s.kind == "use_cases"]
                names, what = [p.use_case], "use case"
            if not relevant:
                continue
            reads = [await self.read(s) for s in relevant]
            known = {i.id for r in reads for i in r.items}
            unknown = [n for n in names if n not in known]
            failed = [r for r in reads if r.error]
            if not unknown:
                continue
            if failed:
                warnings.append(
                    f"Could not check {what} {unknown} against "
                    + "; ".join(f"{r.label} ({r.error})" for r in failed)
                    + ". Accepted unchecked: verify before approving."
                )
            else:
                labels = ", ".join(r.label for r in reads)
                problems.append(f"{what}: {unknown} not in the catalogue of {labels}")
        for kind, code, label, field in _mds_lists():
            names = list(dict.fromkeys(n for p in policies for n in getattr(p, field)))
            if not names:
                continue
            out = await self.read_mds(kind, code, label)
            if out.note:
                continue  # the country has no such list: free text
            known = {i.id for i in out.items}
            unknown = [n for n in names if n not in known]
            if not unknown:
                continue
            what = label.lower()
            if out.error:
                warnings.append(
                    f"Could not check {what} {unknown} against Master Data list {code} "
                    f"({out.error}). Accepted unchecked: verify before approving."
                )
            else:
                problems.append(f"{what}: {unknown} not in Master Data list {code}")
        if problems:
            raise InvalidPolicyError(
                "Unknown " + "; ".join(problems) + ". Choose from the catalogue (GET /catalogue)."
            )
        return warnings
