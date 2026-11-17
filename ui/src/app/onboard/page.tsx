"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useCatalogue } from "@/lib/catalogue";
import { keyAlgorithm } from "@/lib/keyAlgorithm";
import { matchesIdentifier, useMetadata } from "@/lib/metadata";
import { Partner, PartnerKey, PartnerRequest } from "@/lib/types";
import { PageHeader, ErrorBanner, BackLink } from "@/components/ui";
import {
  PolicyEditor,
  PolicyRow,
  emptyPolicy,
  policyRowProblem,
  toPolicyInput,
} from "@/components/policy";

// "auto" = omit algorithm and let the API infer it from the key.
const AUTO = "auto";

interface KeyRow {
  public_key: string;
  kid: string;
  algorithm: string;
}

const emptyKey = (): KeyRow => ({ public_key: "", kid: "", algorithm: AUTO });

function OnboardForm() {
  const router = useRouter();
  const params = useSearchParams();
  const mode = params.get("mode") === "key-update" ? "key-update" : "onboarding";
  const presetPartner = params.get("partner_id") || "";
  const meta = useMetadata();
  const catalogue = useCatalogue();

  const [partnerId, setPartnerId] = useState(presetPartner);
  const [name, setName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [description, setDescription] = useState("");
  const [jwksUrl, setJwksUrl] = useState("");
  const [importJwks, setImportJwks] = useState(false);
  // Onboarding only: read the partner's keys from its JWKS URL when needed.
  const [liveJwks, setLiveJwks] = useState(false);
  const [revokeKids, setRevokeKids] = useState<string[]>([]);
  const [partners, setPartners] = useState<Partner[]>([]);
  const [loadedKeys, setLoadedKeys] = useState<{ partnerId: string; keys: PartnerKey[] }>({
    partnerId: "",
    keys: [],
  });
  const [keys, setKeys] = useState<KeyRow[]>([emptyKey()]);
  // Onboarding only: optional access policies, activated with the partner.
  const [policies, setPolicies] = useState<PolicyRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isUpdate = mode === "key-update";

  // Key update: partner_id must be an existing partner -> offer a select.
  useEffect(() => {
    if (!isUpdate || presetPartner) return;
    api
      .get<{ partners: Partner[] }>("/partners")
      .then((d) => setPartners(d.partners))
      .catch((e) => setError(e.message));
  }, [isUpdate, presetPartner]);

  // Key update: only the partner's current (non-revoked) keys can be revoked.
  useEffect(() => {
    if (!isUpdate || !partnerId) return;
    api
      .get<PartnerKey[]>(`/partners/${encodeURIComponent(partnerId)}/keys`)
      .then((ks) => setLoadedKeys({ partnerId, keys: ks.filter((k) => k.status !== "revoked") }))
      .catch((e) => setError(e.message));
  }, [isUpdate, partnerId]);
  const revocable = loadedKeys.partnerId === partnerId ? loadedKeys.keys : [];

  const partnerIdInvalid =
    !isUpdate && partnerId !== "" && !matchesIdentifier(meta, partnerId);
  const invalidKid = keys.some((k) => k.kid.trim() && !matchesIdentifier(meta, k.kid.trim()));
  // Algorithms of the keys proposed here (chosen, or detected from the key), to
  // pre-fill policies' signing algorithms. undefined while any key is unknown.
  const proposedAlgs = keys
    .filter((k) => k.public_key.trim())
    .map((k) => (k.algorithm !== AUTO ? k.algorithm : keyAlgorithm(k.public_key)));
  const keyAlgs =
    proposedAlgs.length && proposedAlgs.every((a) => a)
      ? Array.from(new Set(proposedAlgs as string[])).sort()
      : undefined;

  const invalidPolicy = !isUpdate && policies.some((p) => policyRowProblem(p) !== null);

  function toggleRevoke(kid: string, on: boolean) {
    setRevokeKids((cur) => (on ? [...cur, kid] : cur.filter((x) => x !== kid)));
  }

  function setPolicy(i: number, patch: Partial<PolicyRow>) {
    setPolicies((ps) => ps.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  }

  function setKey(i: number, patch: Partial<KeyRow>) {
    setKeys((ks) => ks.map((k, idx) => (idx === i ? { ...k, ...patch } : k)));
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const cleanKeys = keys
        .filter((k) => k.public_key.trim())
        .map((k) => ({
          public_key: k.public_key.trim(),
          ...(k.kid.trim() ? { kid: k.kid.trim() } : {}),
          ...(k.algorithm !== AUTO ? { algorithm: k.algorithm } : {}),
        }));

      let req: PartnerRequest;
      if (isUpdate) {
        req = await api.post<PartnerRequest>("/partners/requests/key-update", {
          partner_id: partnerId,
          description,
          jwks_url: jwksUrl || null,
          import_from_jwks_url: importJwks,
          keys: cleanKeys,
          revoke_kids: revokeKids,
        });
      } else {
        req = await api.post<PartnerRequest>("/partners/requests/onboarding", {
          partner_id: partnerId,
          name,
          org_name: orgName || null,
          description,
          jwks_url: jwksUrl || null,
          import_from_jwks_url: importJwks,
          keys_from_jwks_url: liveJwks,
          keys: cleanKeys,
          policies: policies.map(toPolicyInput),
        });
      }
      router.push(`/requests/${req.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-3xl">
      <BackLink href="/partners" label="Partners" />
      <PageHeader
        title={isUpdate ? "Rotate / add keys" : "Onboard a partner"}
        subtitle={
          isUpdate
            ? "File a key-update request for an existing partner"
            : "Register a new partner and its initial public key(s)"
        }
      />
      <ErrorBanner message={error} />

      <div className="card space-y-4">
        <div>
          <label className="field-label">Partner ID *</label>
          {isUpdate && !presetPartner ? (
            <select
              className="field-input"
              value={partnerId}
              onChange={(e) => {
                setPartnerId(e.target.value);
                setRevokeKids([]);
              }}
            >
              <option value="">Select a partner…</option>
              {partners.map((p) => (
                <option key={p.id} value={p.partner_id}>
                  {p.partner_id} — {p.name} ({p.status})
                </option>
              ))}
            </select>
          ) : (
            <>
              <input
                className="field-input"
                value={partnerId}
                disabled={isUpdate}
                onChange={(e) => setPartnerId(e.target.value)}
                placeholder="e.g. PARTNER_G2P_BRIDGE"
                aria-invalid={partnerIdInvalid}
              />
              {!isUpdate && (
                <p
                  className={`text-xs mt-1 ${
                    partnerIdInvalid
                      ? "text-[color:var(--color-danger)]"
                      : "text-[color:var(--color-text-muted)]"
                  }`}
                >
                  Stable ID callers use to fetch keys. {meta.identifier_hint}
                </p>
              )}
            </>
          )}
        </div>

        {!isUpdate && (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="field-label">Name *</label>
              <input
                className="field-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div>
              <label className="field-label">Organisation</label>
              <input
                className="field-input"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
              />
            </div>
          </div>
        )}

        <div>
          <label className="field-label">Description</label>
          <textarea
            className="field-input"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={isUpdate ? "e.g. Scheduled quarterly key rotation" : "Reason for onboarding"}
          />
        </div>

        <div className="border-t border-[color:var(--color-border)] pt-4">
          <div className="flex items-center justify-between mb-2">
            <label className="field-label mb-0">Public keys</label>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setKeys((ks) => [...ks, emptyKey()])}
            >
              + Add key
            </button>
          </div>

          {keys.map((k, i) => (
            <div key={i} className="border border-[color:var(--color-border)] rounded-md p-3 mb-3">
              <div className="flex gap-3 mb-2">
                <div className="flex-1">
                  <label className="field-label">Key ID (optional)</label>
                  <input
                    className="field-input"
                    value={k.kid}
                    onChange={(e) => setKey(i, { kid: e.target.value })}
                    placeholder="defaults to fingerprint"
                    aria-invalid={!!k.kid.trim() && !matchesIdentifier(meta, k.kid.trim())}
                  />
                  {k.kid.trim() && !matchesIdentifier(meta, k.kid.trim()) && (
                    <p className="text-xs mt-1 text-[color:var(--color-danger)]">
                      {meta.identifier_hint}
                    </p>
                  )}
                </div>
                <div className="w-40">
                  <label className="field-label">Algorithm</label>
                  <select
                    className="field-input"
                    value={k.algorithm}
                    onChange={(e) => setKey(i, { algorithm: e.target.value })}
                  >
                    <option value={AUTO}>Auto-detect</option>
                    {meta.algorithms.map((a) => (
                      <option key={a} value={a}>
                        {a}
                      </option>
                    ))}
                  </select>
                </div>
                {keys.length > 1 && (
                  <button
                    type="button"
                    className="btn-secondary self-end"
                    onClick={() => setKeys((ks) => ks.filter((_, idx) => idx !== i))}
                  >
                    Remove
                  </button>
                )}
              </div>
              <label className="field-label">PEM (SPKI or X.509 certificate) or JWK JSON</label>
              <textarea
                className="field-input font-mono text-xs"
                rows={5}
                value={k.public_key}
                onChange={(e) => setKey(i, { public_key: e.target.value })}
                placeholder="-----BEGIN PUBLIC KEY-----&#10;...&#10;-----END PUBLIC KEY-----"
              />
            </div>
          ))}
        </div>

        <div className="border-t border-[color:var(--color-border)] pt-4">
          <label className="field-label">JWKS URL (optional)</label>
          <input
            className="field-input"
            type="url"
            value={jwksUrl}
            onChange={(e) => {
              setJwksUrl(e.target.value);
              if (!e.target.value.trim()) {
                setImportJwks(false);
                setLiveJwks(false);
              }
            }}
            placeholder="https://partner.example.org/.well-known/jwks.json"
          />
          <label className="flex items-center gap-2 mt-2 text-sm">
            <input
              type="checkbox"
              checked={importJwks}
              disabled={!jwksUrl.trim()}
              onChange={(e) => setImportJwks(e.target.checked)}
            />
            Import keys from this JWKS URL now (fetched once and stored)
          </label>
          {!isUpdate && (
            <label className="flex items-center gap-2 mt-2 text-sm">
              <input
                type="checkbox"
                checked={liveJwks}
                disabled={!jwksUrl.trim()}
                onChange={(e) => setLiveJwks(e.target.checked)}
              />
              Read keys from this JWKS URL whenever they are needed (the partner rotates its own
              keys; no key needed now)
            </label>
          )}
        </div>

        {isUpdate && (
          <div>
            <label className="field-label">Revoke existing keys (optional)</label>
            {!partnerId ? (
              <p className="text-sm text-[color:var(--color-text-muted)]">
                Select a partner to see its keys.
              </p>
            ) : revocable.length === 0 ? (
              <p className="text-sm text-[color:var(--color-text-muted)]">
                This partner has no current keys to revoke.
              </p>
            ) : (
              <div className="space-y-1">
                {revocable.map((k) => (
                  <label key={k.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={revokeKids.includes(k.kid)}
                      onChange={(e) => toggleRevoke(k.kid, e.target.checked)}
                    />
                    <span className="font-medium">{k.kid}</span>
                    <span className="text-[color:var(--color-text-muted)]">
                      {k.algorithm} · {k.status}
                      {k.key_fingerprint ? ` · ${k.key_fingerprint.slice(0, 16)}…` : ""}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        {!isUpdate && (
          <div className="border-t border-[color:var(--color-border)] pt-4">
            <div className="flex items-center justify-between mb-2">
              <label className="field-label mb-0">Policies (optional)</label>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setPolicies((ps) => [...ps, emptyPolicy()])}
              >
                + Add policy
              </button>
            </div>
            <p className="text-xs mb-2 text-[color:var(--color-text-muted)]">
              What this partner may ask for: one policy per registry (its scopes) and one per
              use case of an exchange; add as many as needed. Activated when the onboarding is
              approved; change later from the partner page.
            </p>
            {policies.map((p, i) => (
              <PolicyEditor
                key={i}
                row={p}
                meta={meta}
                catalogue={catalogue}
                keyAlgs={keyAlgs}
                onChange={(patch) => setPolicy(i, patch)}
                onRemove={() => setPolicies((ps) => ps.filter((_, idx) => idx !== i))}
              />
            ))}
          </div>
        )}

        <div className="flex gap-3 pt-2">
          <button
            className="btn-primary"
            disabled={busy || !partnerId || partnerIdInvalid || invalidKid || invalidPolicy}
            onClick={submit}
          >
            {busy ? "Submitting…" : "Submit request"}
          </button>
          <button className="btn-secondary" onClick={() => router.back()}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export default function OnboardPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <OnboardForm />
    </Suspense>
  );
}
