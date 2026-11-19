"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useMetadata } from "@/lib/metadata";
import { Partner } from "@/lib/types";
import { PageHeader, StatusPill, ErrorBanner, Empty, fmtDate } from "@/components/ui";

export default function PartnersPage() {
  const meta = useMetadata();
  const [rows, setRows] = useState<Partner[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<{ partners: Partner[] }>(
        `/partners${status ? `?status=${encodeURIComponent(status)}` : ""}`
      )
      .then((d) => setRows(d.partners))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [status]);

  return (
    <div>
      <PageHeader
        title="Partners"
        subtitle="Registered partners and their status"
        action={
          <div className="flex items-center gap-2">
            <select
              className="field-input w-48"
              aria-label="Partner status"
              value={status}
              onChange={(e) => {
                setLoading(true);
                setError(null);
                setStatus(e.target.value);
              }}
            >
              <option value="">All statuses</option>
              {meta.partner_statuses.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <Link href="/onboard" className="btn-primary whitespace-nowrap">
              + Onboard partner
            </Link>
          </div>
        }
      />
      <ErrorBanner message={error} />

      {loading ? (
        <Empty message="Loading…" />
      ) : rows.length === 0 ? (
        <Empty
          message={
            status
              ? `No ${status} partners.`
              : "No partners yet. Onboard one to get started."
          }
        />
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Partner ID</th>
                <th>Name</th>
                <th>Organisation</th>
                <th>Status</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td className="font-medium">{p.partner_id}</td>
                  <td>{p.name}</td>
                  <td>{p.org_name || "—"}</td>
                  <td>
                    <StatusPill status={p.status} />
                  </td>
                  <td>{fmtDate(p.created_at)}</td>
                  <td>
                    <Link
                      href={`/partners/${encodeURIComponent(p.partner_id)}`}
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
  );
}
