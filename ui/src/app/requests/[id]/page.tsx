"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { labelOf } from "@/lib/metadata";
import { PartnerRequest } from "@/lib/types";
import { PolicySummary, policyKeyId, policyKeyLabel } from "@/components/policy";
import {
  PageHeader,
  StatusPill,
  BackLink,
  ErrorBanner,
  fmtDate,
} from "@/components/ui";

export default function RequestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [req, setReq] = useState<PartnerRequest | null>(null);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    api
      .get<PartnerRequest>(`/partners/requests/${id}`)
      .then(setReq)
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, [id]);

  async function decide(action: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.post<PartnerRequest>(
        `/partners/requests/${id}/${action}`,
        { notes }
      );
      setReq(updated);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!req) {
    return (
      <div>
        <BackLink href="/requests" label="Approvals" />
        <ErrorBanner message={error} />
        {!error && <p className="mt-4">Loading…</p>}
      </div>
    );
  }

  const open = req.status === "created";

  return (
    <div>
      <BackLink href="/requests" label="Approvals" />
      <PageHeader
        title={`${labelOf(req.request_type)} — ${req.partner_id}`}
        subtitle={`Filed ${fmtDate(req.created_at)}`}
        action={<StatusPill status={req.status} />}
      />

      <ErrorBanner message={error} />

      {req.warnings?.length > 0 && (
        <div className="card mb-4 border-[color:var(--color-brand-orange)]">
          <h2 className="text-lg mb-2">Not checked at submission</h2>
          <ul className="list-disc pl-5 text-sm space-y-1">
            {req.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="card">
          <h2 className="text-lg mb-3">Partner</h2>
          <Detail label="Partner ID" value={req.partner_id} />
          <Detail label="Name" value={req.name} />
          <Detail label="Organisation" value={req.org_name} />
          <Detail
            label="JWKS URL"
            value={
              req.jwks_url && req.keys_from_jwks_url
                ? `${req.jwks_url} (keys read from it when needed)`
                : req.jwks_url
            }
          />
          <Detail label="Description" value={req.description} />
          <Detail label="Submitted by" value={req.submitted_by} />
          {req.reviewed_by && <Detail label="Reviewed by" value={req.reviewed_by} />}
          {req.review_notes && <Detail label="Review notes" value={req.review_notes} />}
        </div>

        {req.request_type !== "policy" && (
          <div className="card">
            <h2 className="text-lg mb-3">Proposed keys</h2>
            {req.proposed_keys?.length ? (
              <ul className="space-y-3">
                {req.proposed_keys.map((k) => (
                  <li key={k.kid} className="border border-[color:var(--color-border)] rounded-md p-3">
                    <div className="font-medium">{k.kid}</div>
                    <div className="text-sm text-[color:var(--color-text-muted)]">
                      {k.algorithm}
                      {k.key_fingerprint ? ` · ${k.key_fingerprint.slice(0, 16)}…` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[color:var(--color-text-muted)]">No new keys.</p>
            )}
            {req.revoke_kids?.length > 0 && (
              <div className="mt-3 text-sm">
                <span className="text-[color:var(--color-text-muted)]">Revoking: </span>
                {req.revoke_kids.join(", ")}
              </div>
            )}
          </div>
        )}
      </div>

      {(req.proposed_policies?.length > 0 || req.revoke?.length > 0) && (
        <div className="card mb-4">
          <h2 className="text-lg mb-3">Proposed policies</h2>
          {req.proposed_policies?.length ? (
            <ul className="space-y-3">
              {req.proposed_policies.map((p) => (
                <li
                  key={policyKeyId(p)}
                  className="border border-[color:var(--color-border)] rounded-md p-3"
                >
                  <div className="font-medium mb-1">{policyKeyLabel(p)}</div>
                  <PolicySummary policy={p} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[color:var(--color-text-muted)]">No new policy versions.</p>
          )}
          {req.revoke?.length > 0 && (
            <ul className="mt-3 text-sm space-y-1">
              {req.revoke.map((r) => (
                <li key={policyKeyId(r)}>
                  <span className="text-[color:var(--color-danger)]">Revoke </span>
                  {policyKeyLabel(r)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {open ? (
        <div className="card">
          <h2 className="text-lg mb-3">Decision</h2>
          <label className="field-label">Review notes (optional)</label>
          <textarea
            className="field-input"
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div className="flex gap-3 mt-4">
            <button
              className="btn-primary"
              disabled={busy}
              onClick={() => decide("approve")}
            >
              Approve
            </button>
            <button
              className="btn-danger"
              disabled={busy}
              onClick={() => decide("reject")}
            >
              Reject
            </button>
            <button className="btn-secondary" onClick={() => router.push("/requests")}>
              Back
            </button>
          </div>
        </div>
      ) : (
        <div className="card text-[color:var(--color-text-muted)]">
          This request has been {req.status}.
        </div>
      )}
    </div>
  );
}

function Detail({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="mb-2">
      <div className="text-xs text-[color:var(--color-text-muted)]">{label}</div>
      <div className="break-words">{value || "—"}</div>
    </div>
  );
}
