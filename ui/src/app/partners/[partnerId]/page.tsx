"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { AuditEvent, Partner, PartnerKey, PartnerPolicy, PartnerRequest } from "@/lib/types";
import { labelOf } from "@/lib/metadata";
import { policyKeyId, policyKeyLabel, policyRef } from "@/components/policy";
import {
  PageHeader,
  StatusPill,
  BackLink,
  ErrorBanner,
  fmtDate,
} from "@/components/ui";

export default function PartnerDetailPage() {
  const params = useParams<{ partnerId: string }>();
  const partnerId = decodeURIComponent(params.partnerId);
  const router = useRouter();
  const [partner, setPartner] = useState<Partner | null>(null);
  const [keys, setKeys] = useState<PartnerKey[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  // Every version; the active ones are shown first, the rest under history.
  const [policies, setPolicies] = useState<PartnerPolicy[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  // Open policy requests: a policy with a pending change cannot be edited or revoked.
  const [openPolicyReqs, setOpenPolicyReqs] = useState<PartnerRequest[]>([]);
  // The policy whose revocation is being confirmed, and the request's description.
  const [revoking, setRevoking] = useState<PartnerPolicy | null>(null);
  const [revokeWhy, setRevokeWhy] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, k, pol, a, reqs] = await Promise.all([
        api.get<Partner>(`/partners/${encodeURIComponent(partnerId)}`),
        api.get<PartnerKey[]>(`/partners/${encodeURIComponent(partnerId)}/keys`),
        api.get<PartnerPolicy[]>(
          `/partners/${encodeURIComponent(partnerId)}/policies?all_versions=true`
        ),
        api.get<{ events: AuditEvent[] }>(
          `/partners/${encodeURIComponent(partnerId)}/audit`
        ),
        api.get<{ requests: PartnerRequest[] }>(
          `/partners/requests?partner_id=${encodeURIComponent(partnerId)}&status=created`
        ),
      ]);
      setPartner(p);
      setKeys(k);
      setPolicies(pol);
      setAudit(a.events);
      setOpenPolicyReqs(reqs.requests);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [partnerId]);

  useEffect(() => {
    load();
  }, [load]);

  async function toggle(action: "disable" | "enable") {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/partners/${encodeURIComponent(partnerId)}/${action}`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(p: PartnerPolicy) {
    setBusy(true);
    setError(null);
    try {
      const req = await api.post<PartnerRequest>("/partners/requests/policy", {
        partner_id: partnerId,
        description: revokeWhy || null,
        revoke: [policyRef(p)],
      });
      router.push(`/requests/${req.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  if (!partner) {
    return (
      <div>
        <BackLink href="/partners" label="Partners" />
        <ErrorBanner message={error} />
        {!error && <p className="mt-4">Loading…</p>}
      </div>
    );
  }

  // One row per policy key: its active version, else (a new policy) its pending one.
  const current = policies.filter(
    (p) =>
      p.status === "active" ||
      (p.status === "pending" &&
        !policies.some((q) => q.status === "active" && policyKeyId(q) === policyKeyId(p))),
  );
  const history = policies.filter((p) => !current.includes(p));
  // Key → open request changing (pending version) or revoking it.
  const pendingReq = new Map<string, string>();
  for (const p of policies)
    if (p.status === "pending") pendingReq.set(policyKeyId(p), p.request_id);
  for (const r of openPolicyReqs)
    for (const ref of r.revoke || []) pendingReq.set(policyKeyId(ref), r.id);
  const policyBase = `/partners/${encodeURIComponent(partnerId)}/policy`;

  return (
    <div>
      <BackLink href="/partners" label="Partners" />
      <PageHeader
        title={partner.partner_id}
        subtitle={partner.name}
        action={
          <div className="flex items-center gap-3">
            <StatusPill status={partner.status} />
            {partner.status === "disabled" ? (
              <button className="btn-primary" disabled={busy} onClick={() => toggle("enable")}>
                Enable
              </button>
            ) : (
              <button className="btn-danger" disabled={busy} onClick={() => toggle("disable")}>
                Disable
              </button>
            )}
          </div>
        }
      />

      <ErrorBanner message={error} />

      <div className="card mb-4">
        <div className="grid grid-cols-2 gap-x-8 gap-y-2">
          <Detail label="Organisation" value={partner.org_name} />
          <Detail
            label="JWKS URL"
            value={
              partner.jwks_url
                ? partner.keys_from_jwks_url
                  ? `${partner.jwks_url} (keys read from it when needed)`
                  : partner.jwks_url
                : null
            }
          />
          <Detail label="Created by" value={partner.created_by} />
          <Detail label="Approved by" value={partner.approved_by} />
          <Detail label="Created" value={fmtDate(partner.created_at)} />
          <Detail label="Description" value={partner.description} />
        </div>
      </div>

      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg">Keys</h2>
        <Link
          href={`/onboard?mode=key-update&partner_id=${encodeURIComponent(partner.partner_id)}`}
          className="btn-secondary"
        >
          Rotate / add keys
        </Link>
      </div>

      {keys.length === 0 ? (
        <div className="card text-[color:var(--color-text-muted)]">No keys.</div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Key ID</th>
                <th>Algorithm</th>
                <th>Fingerprint</th>
                <th>Status</th>
                <th>Not before</th>
                <th>Not after</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id}>
                  <td className="font-medium">{k.kid}</td>
                  <td>{k.algorithm}</td>
                  <td title={k.key_fingerprint || ""}>
                    {k.key_fingerprint ? k.key_fingerprint.slice(0, 16) + "…" : "—"}
                  </td>
                  <td>
                    <StatusPill status={k.status} />
                  </td>
                  <td>{fmtDate(k.not_before)}</td>
                  <td>{fmtDate(k.not_after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between mt-6 mb-3">
        <h2 className="text-lg">Policies</h2>
        {partner.status === "active" && (
          <Link href={policyBase} className="btn-secondary">
            Add policy
          </Link>
        )}
      </div>

      {current.length === 0 ? (
        <div className="card text-[color:var(--color-text-muted)]">No policies.</div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Policy</th>
                <th>Version</th>
                <th>Status</th>
                <th>Summary</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {current.map((p) => {
                const pending = pendingReq.get(policyKeyId(p));
                const editable = partner.status === "active" && p.status === "active";
                return (
                  <tr key={p.id}>
                    <td className="font-medium whitespace-nowrap">{policyKeyLabel(p)}</td>
                    <td>
                      v{p.version}
                      {p.effective_from && (
                        <span className="block text-xs text-[color:var(--color-text-muted)]">
                          since {fmtDate(p.effective_from)}
                        </span>
                      )}
                    </td>
                    <td>
                      <StatusPill status={p.status} />
                    </td>
                    <td className="text-sm">{policySummaryLine(p)}</td>
                    <td className="whitespace-nowrap text-right">
                      {pending ? (
                        <Link
                          href={`/requests/${pending}`}
                          className="text-sm underline underline-offset-2"
                        >
                          Change pending
                        </Link>
                      ) : (
                        editable && (
                          <div className="flex gap-2 justify-end">
                            <Link
                              href={`${policyBase}?${new URLSearchParams(
                                policyRef(p) as Record<string, string>,
                              )}`}
                              className="btn-secondary"
                            >
                              Edit
                            </Link>
                            <button
                              className="btn-danger"
                              disabled={busy}
                              onClick={() => {
                                setRevoking(p);
                                setRevokeWhy("");
                              }}
                            >
                              Revoke
                            </button>
                          </div>
                        )
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {revoking && (
        <div className="card mt-3 space-y-3">
          <p>
            Revoke <span className="font-medium">{policyKeyLabel(revoking)}</span> (v
            {revoking.version})? This raises a policy request; the policy stays in force until
            the request is approved.
          </p>
          <textarea
            className="field-input"
            rows={2}
            value={revokeWhy}
            onChange={(e) => setRevokeWhy(e.target.value)}
            placeholder="Why the policy is revoked"
          />
          <div className="flex gap-3">
            <button className="btn-danger" disabled={busy} onClick={() => revoke(revoking)}>
              {busy ? "Submitting…" : "Raise revoke request"}
            </button>
            <button className="btn-secondary" onClick={() => setRevoking(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {history.length > 0 && (
        <div className="mt-3">
          <button
            type="button"
            className="text-sm underline underline-offset-2"
            onClick={() => setShowHistory((v) => !v)}
          >
            {showHistory ? "Hide" : "Show"} policy version history ({history.length})
          </button>
          {showHistory && (
            <div className="card p-0 overflow-hidden mt-3">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Policy</th>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Summary</th>
                    <th>Created</th>
                    <th>Request</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((p) => (
                    <tr key={p.id}>
                      <td className="font-medium whitespace-nowrap">{policyKeyLabel(p)}</td>
                      <td>v{p.version}</td>
                      <td>
                        <StatusPill status={p.status} />
                      </td>
                      <td className="text-sm text-[color:var(--color-text-muted)]">
                        {policySummaryLine(p)}
                      </td>
                      <td>{fmtDate(p.created_at)}</td>
                      <td>
                        <Link
                          href={`/requests/${p.request_id}`}
                          className="text-sm underline underline-offset-2"
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <h2 className="text-lg mt-6 mb-3">History</h2>
      {audit.length === 0 ? (
        <div className="card text-[color:var(--color-text-muted)]">No activity yet.</div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Action</th>
                <th>By</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap">{fmtDate(e.created_at)}</td>
                  <td className="font-medium">{e.action}</td>
                  <td>{e.actor_name || "—"}</td>
                  <td className="text-[color:var(--color-text-muted)]">
                    {Object.keys(e.details || {}).length
                      ? JSON.stringify(e.details)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// One line: scopes and purposes (registry), algorithms, validity, fetch.
function policySummaryLine(p: PartnerPolicy) {
  const any = (v: string[]) => (v.length ? v.join(", ") : "any");
  return [
    p.data_controller ? `Scopes: ${p.allowed_data_scopes.join(", ")}` : null,
    p.data_controller ? `Purposes: ${any(p.allowed_purposes)}` : null,
    p.allowed_subject_id_types.length ? `ID types: ${p.allowed_subject_id_types.join(", ")}` : null,
    `Algs: ${p.allowed_signing_algs.join(", ")}`,
    p.max_validity_duration ? `Validity ≤ ${p.max_validity_duration}` : null,
    labelOf(p.fetch_type),
    p.allow_partner_consents ? "Own signed consents" : null,
    p.allow_assisted_confirmation ? "Assisted confirmation" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function Detail({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <div className="text-xs text-[color:var(--color-text-muted)]">{label}</div>
      <div className="break-words">{value || "—"}</div>
    </div>
  );
}
