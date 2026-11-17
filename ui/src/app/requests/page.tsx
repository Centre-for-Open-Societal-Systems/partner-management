"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { labelOf, useMetadata } from "@/lib/metadata";
import { PartnerRequest } from "@/lib/types";
import { PageHeader, StatusPill, ErrorBanner, Empty, fmtDate } from "@/components/ui";

export default function RequestsPage() {
  const [rows, setRows] = useState<PartnerRequest[]>([]);
  const meta = useMetadata();
  const [status, setStatus] = useState("");
  const [requestType, setRequestType] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    if (requestType) qs.set("request_type", requestType);
    const q = qs.toString();
    api
      .get<{ requests: PartnerRequest[] }>(`/partners/requests${q ? `?${q}` : ""}`)
      .then((d) => setRows(d.requests))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [status, requestType]);

  return (
    <div>
      <PageHeader
        title="Approvals"
        subtitle="Requests to onboard a partner, change its keys or change its policies, approved or rejected here"
      />

      <div className="flex flex-wrap items-center gap-2 mb-4">
        {["", ...meta.request_statuses].map((f) => (
          <button
            key={f || "all"}
            onClick={() => setStatus(f)}
            className={status === f ? "btn-primary" : "btn-secondary"}
          >
            {f || "All"}
          </button>
        ))}
        <select
          className="field-input w-48 ml-auto"
          aria-label="Request type"
          value={requestType}
          onChange={(e) => setRequestType(e.target.value)}
        >
          <option value="">All types</option>
          {meta.request_types.map((t) => (
            <option key={t} value={t}>
              {labelOf(t)}
            </option>
          ))}
        </select>
      </div>

      <ErrorBanner message={error} />

      {loading ? (
        <Empty message="Loading…" />
      ) : rows.length === 0 ? (
        <Empty message="No requests found." />
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Partner ID</th>
                <th>Type</th>
                <th>Changes</th>
                <th>Status</th>
                <th>Submitted by</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="font-medium">{r.partner_id}</td>
                  <td>{labelOf(r.request_type)}</td>
                  <td>{changesOf(r)}</td>
                  <td>
                    <StatusPill status={r.status} />
                  </td>
                  <td>{r.submitted_by || "—"}</td>
                  <td>{fmtDate(r.created_at)}</td>
                  <td>
                    <Link
                      href={`/requests/${r.id}`}
                      className="text-sm underline underline-offset-2"
                    >
                      Review
                    </Link>
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

// e.g. "+1 key / −1 key · +2 policies".
function changesOf(r: PartnerRequest): string {
  const part = (added: number, removed: number, one: string, many: string) =>
    [added ? `+${added} ${added === 1 ? one : many}` : "", removed ? `−${removed} ${removed === 1 ? one : many}` : ""]
      .filter(Boolean)
      .join(" / ");
  const keys = part(r.proposed_keys?.length || 0, r.revoke_kids?.length || 0, "key", "keys");
  const policies = part(
    r.proposed_policies?.length || 0,
    r.revoke?.length || 0,
    "policy",
    "policies"
  );
  return [keys, policies].filter(Boolean).join(" · ") || "—";
}
