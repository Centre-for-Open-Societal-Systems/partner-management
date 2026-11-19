"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useCatalogue } from "@/lib/catalogue";
import { useMetadata } from "@/lib/metadata";
import { PartnerKey, PartnerPolicy, PartnerRequest } from "@/lib/types";
import { PageHeader, BackLink, ErrorBanner } from "@/components/ui";
import {
  PolicyEditor,
  PolicyRow,
  emptyPolicy,
  policyKeyId,
  policyKeyLabel,
  policyRowFrom,
  policyRowProblem,
  toPolicyInput,
} from "@/components/policy";

// One policy request for one policy:
//   ?data_controller=X or ?use_case=Y  → Edit that active policy (its next version);
//   no key                            → Add a policy (registry or use case).
export default function PolicyPage() {
  return (
    <Suspense fallback={<p className="mt-4">Loading…</p>}>
      <PolicyForm />
    </Suspense>
  );
}

function PolicyForm() {
  const params = useParams<{ partnerId: string }>();
  const partnerId = decodeURIComponent(params.partnerId);
  const search = useSearchParams();
  const editKey = search.get("data_controller")
    ? { data_controller: search.get("data_controller") }
    : search.get("use_case")
      ? { use_case: search.get("use_case") }
      : null;
  const router = useRouter();
  const meta = useMetadata();
  const catalogue = useCatalogue();

  const [active, setActive] = useState<PartnerPolicy[] | null>(null);
  // Algorithms of the partner's active keys (pre-fill a new policy's algorithms).
  const [keyAlgs, setKeyAlgs] = useState<string[] | undefined>(undefined);
  const [row, setRow] = useState<PolicyRow | null>(editKey ? null : emptyPolicy());
  const [current, setCurrent] = useState<PartnerPolicy | null>(null);
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<PartnerPolicy[]>(`/partners/${encodeURIComponent(partnerId)}/policies`)
      .then((ps) => {
        setActive(ps);
        if (!editKey) return;
        const p = ps.find((x) => policyKeyId(x) === policyKeyId(editKey));
        if (!p) setError(`No active policy for ${policyKeyLabel(editKey)}.`);
        else {
          setCurrent(p);
          setRow(policyRowFrom(p));
        }
      })
      .catch((e) => setError(e.message));
    api
      .get<PartnerKey[]>(`/partners/${encodeURIComponent(partnerId)}/keys`)
      .then((ks) =>
        setKeyAlgs(
          Array.from(new Set(ks.filter((k) => k.status === "active").map((k) => k.algorithm))).sort(),
        ),
      )
      .catch(() => setKeyAlgs(undefined)); // only a pre-fill: the form works without it
  }, [partnerId, search]);

  // Adding a key that already has an active policy makes its next version.
  const existing =
    !editKey && row
      ? active?.find((p) => policyKeyId(p) === policyKeyId(toPolicyInput(row)))
      : undefined;

  async function submit() {
    if (!row) return;
    setBusy(true);
    setError(null);
    try {
      const req = await api.post<PartnerRequest>("/partners/requests/policy", {
        partner_id: partnerId,
        description: description || null,
        policies: [toPolicyInput(row)],
      });
      router.push(`/requests/${req.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-3xl">
      <BackLink href={`/partners/${encodeURIComponent(partnerId)}`} label={partnerId} />
      <PageHeader
        title={editKey ? `Edit policy — ${policyKeyLabel(editKey)}` : "Add policy"}
        subtitle={
          current
            ? `Raises a policy request for version ${current.version + 1}; v${current.version} stays in force until it is approved`
            : `Raises a policy request for ${partnerId}; the policy applies on approval`
        }
      />
      <ErrorBanner message={error} />

      {row && (
        <div className="card space-y-4">
          <PolicyEditor
            row={row}
            meta={meta}
            catalogue={catalogue}
            lockKey={!!editKey}
            keyAlgs={keyAlgs}
            onChange={(patch) => setRow((r) => (r ? { ...r, ...patch } : r))}
          />
          {existing && (
            <p className="text-sm text-[color:var(--color-text-muted)]">
              {partnerId} already has {policyKeyLabel(existing)} (v{existing.version}): this
              request makes its version {existing.version + 1}.
            </p>
          )}

          <div>
            <label className="field-label">Description</label>
            <textarea
              className="field-input"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Why the policy is changing"
            />
          </div>

          <div className="flex gap-3 pt-2">
            <button
              className="btn-primary"
              disabled={busy || policyRowProblem(row) !== null}
              onClick={submit}
            >
              {busy ? "Submitting…" : "Submit request"}
            </button>
            <button className="btn-secondary" onClick={() => router.back()}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
