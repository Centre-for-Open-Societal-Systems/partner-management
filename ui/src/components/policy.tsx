"use client";

import { useEffect, useState } from "react";
import { CatalogueItem, CatalogueSource } from "@/lib/catalogue";
import { Metadata, labelOf } from "@/lib/metadata";
import { PolicyInput, PolicyRef } from "@/lib/types";

// Form state for one policy. List fields are comma-separated text; the API
// trims entries and drops blanks/duplicates.
export interface PolicyRow {
  kind: "registry" | "use_case";
  data_controller: string; // registry
  use_case: string; // use case (name@major)
  scopes: string; // registry
  purposes: string;
  subject_id_types: string;
  signing_algs: string[];
  // New rows follow the partner's key algorithms until the user ticks a box.
  algs_from_keys: boolean;
  max_validity_duration: string;
  fetch_type: string;
  max_fetch_frequency: string;
  data_life: string;
  allow_partner_consents: boolean;
  allow_assisted_confirmation: boolean;
}

export const DEFAULT_SIGNING_ALGS = ["EdDSA", "ES256"];

export const emptyPolicy = (kind: PolicyRow["kind"] = "registry"): PolicyRow => ({
  kind,
  data_controller: "",
  use_case: "",
  scopes: "",
  purposes: "",
  subject_id_types: "",
  signing_algs: [...DEFAULT_SIGNING_ALGS],
  algs_from_keys: true,
  max_validity_duration: "",
  fetch_type: "oneshot",
  max_fetch_frequency: "",
  data_life: "",
  allow_partner_consents: false,
  allow_assisted_confirmation: false,
});

const splitList = (v: string) =>
  v
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

export function policyRowFrom(p: PolicyInput): PolicyRow {
  return {
    kind: p.data_controller ? "registry" : "use_case",
    data_controller: p.data_controller || "",
    use_case: p.use_case || "",
    scopes: p.allowed_data_scopes.join(", "),
    purposes: p.allowed_purposes.join(", "),
    subject_id_types: p.allowed_subject_id_types.join(", "),
    signing_algs: [...p.allowed_signing_algs],
    algs_from_keys: false,
    max_validity_duration: p.max_validity_duration || "",
    fetch_type: p.fetch_type,
    max_fetch_frequency: p.max_fetch_frequency || "",
    data_life: p.data_life || "",
    allow_partner_consents: !!p.allow_partner_consents,
    allow_assisted_confirmation: !!p.allow_assisted_confirmation,
  };
}

export function toPolicyInput(r: PolicyRow): PolicyInput {
  const isRegistry = r.kind === "registry";
  return {
    data_controller: isRegistry ? r.data_controller.trim() : null,
    use_case: isRegistry ? null : r.use_case.trim(),
    allowed_data_scopes: isRegistry ? splitList(r.scopes) : [],
    // A use-case policy lists no purposes: granting the use case grants its purpose.
    allowed_purposes: isRegistry ? splitList(r.purposes) : [],
    allowed_subject_id_types: splitList(r.subject_id_types),
    allowed_signing_algs: r.signing_algs,
    max_validity_duration: r.max_validity_duration.trim() || null,
    fetch_type: r.fetch_type,
    max_fetch_frequency: r.max_fetch_frequency.trim() || null,
    data_life: r.data_life.trim() || null,
    allow_partner_consents: r.allow_partner_consents,
    allow_assisted_confirmation: r.allow_assisted_confirmation,
  };
}

// The policy's key: {data_controller} or {use_case}.
export function policyRef(p: PolicyRef): PolicyRef {
  return p.data_controller ? { data_controller: p.data_controller } : { use_case: p.use_case };
}

// "Registry: farmer_registry" / "Use case: loan-profile@1".
export function policyKeyLabel(p: PolicyRef) {
  return p.data_controller ? `Registry: ${p.data_controller}` : `Use case: ${p.use_case}`;
}

// A string id for the key (React keys, sets).
export function policyKeyId(p: PolicyRef) {
  return p.data_controller ? `dc:${p.data_controller}` : `uc:${p.use_case}`;
}

// Blocking problems the API would also reject, so the submit button can say why.
export function policyRowProblem(r: PolicyRow): string | null {
  if (r.kind === "registry") {
    if (!r.data_controller.trim()) return "Registry (data controller) is required.";
    if (!splitList(r.scopes).length) return "At least one scope is required.";
  } else if (!/^[^\s/?#%@]+@\d+$/.test(r.use_case.trim())) {
    return "Use case is required, as name@major (e.g. loan-profile@1).";
  }
  if (!r.signing_algs.length) return "At least one signing algorithm is required.";
  return null;
}

const OTHER = "__other__";

const uniqueItems = (sources: CatalogueSource[]) =>
  Array.from(new Map(sources.flatMap((s) => s.items).map((i) => [i.id, i] as const)).values());

// Checkbox list of catalogue items, each with its label and description (and a
// use case's purpose). Selected IDs the catalogue does not list stay visible so
// they can be unticked.
function CatalogueChoices({
  items,
  selected,
  showUnlisted,
  onChange,
}: {
  items: CatalogueItem[];
  selected: string[];
  showUnlisted: boolean;
  onChange: (ids: string[]) => void;
}) {
  const muted = "text-[color:var(--color-text-muted)]";
  const listed = new Set(items.map((i) => i.id));
  const unlisted = showUnlisted ? selected.filter((id) => !listed.has(id)) : [];
  const toggle = (id: string, on: boolean) =>
    onChange(on ? [...selected, id] : selected.filter((x) => x !== id));
  return (
    <div className="space-y-2 max-h-72 overflow-y-auto">
      {items.map((i) => (
        <label key={i.id} className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={selected.includes(i.id)}
            onChange={(e) => toggle(i.id, e.target.checked)}
          />
          <span>
            <span className="font-medium">{i.label || i.id}</span>{" "}
            <span className={muted}>({i.id})</span>
            {i.description && <span className={`block ${muted}`}>{i.description}</span>}
            {i.purpose && <span className={`block ${muted}`}>Purpose: {i.purpose}</span>}
            {!!i.fields?.length && (
              <span className={`block text-xs ${muted}`}>Fields: {i.fields.join(", ")}</span>
            )}
          </span>
        </label>
      ))}
      {unlisted.map((id) => (
        <label key={id} className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" checked onChange={() => toggle(id, false)} />
          <span>
            <span className="font-medium">{id}</span>{" "}
            <span className="text-[color:var(--color-danger)]">not in the catalogue</span>
          </span>
        </label>
      ))}
    </div>
  );
}

// Purposes / subject ID types: the Master Data list's checklist when it loaded;
// free text when it is not configured, not in the country's pack (note), or
// could not be read (error: the request will carry a warning).
function CodeListField({
  label,
  value,
  source,
  onChange,
}: {
  label: string;
  value: string;
  source?: CatalogueSource;
  onChange: (v: string) => void;
}) {
  const muted = "text-xs mt-1 text-[color:var(--color-text-muted)]";
  const listed = source && !source.error && !source.note && source.items.length > 0;
  return (
    <div>
      <label className="field-label">{label}</label>
      {listed ? (
        <>
          <CatalogueChoices
            items={source.items}
            selected={splitList(value)}
            showUnlisted
            onChange={(ids) => onChange(ids.join(", "))}
          />
          <p className={muted}>From {source.label}. None ticked = any.</p>
        </>
      ) : (
        <>
          <input
            className="field-input"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="empty = any"
          />
          {source?.error && (
            <p className="text-xs mt-1 text-[color:var(--color-danger)]">
              {source.label}: {source.error}. Enter codes by hand; the request will carry a
              warning.
            </p>
          )}
          {source?.note && <p className={muted}>{source.note}</p>}
        </>
      )}
    </div>
  );
}

const sameSet = (a: string[], b: string[]) =>
  a.length === b.length && a.every((x) => b.includes(x));

export function PolicyEditor({
  row,
  meta,
  catalogue = [],
  onChange,
  onRemove,
  lockKey,
  keyAlgs,
}: {
  row: PolicyRow;
  meta: Metadata;
  // GET /catalogue sources; empty = free-text registry, scopes and use case.
  catalogue?: CatalogueSource[];
  onChange: (patch: Partial<PolicyRow>) => void;
  onRemove?: () => void;
  // Editing an existing policy: its registry / use case cannot change.
  lockKey?: boolean;
  // Algorithms of the partner's active (or proposed) keys; undefined = unknown.
  keyAlgs?: string[];
}) {
  const muted = "text-sm text-[color:var(--color-text-muted)]";
  const danger = "text-xs mb-1 text-[color:var(--color-danger)]";
  const isRegistry = row.kind === "registry";
  const problem = policyRowProblem(row);

  // Pre-fill signing algorithms from the partner's keys (new rows, until edited).
  const keyAlgsAllowed = (keyAlgs ?? []).filter((a) => meta.signing_algorithms.includes(a));
  useEffect(() => {
    if (row.algs_from_keys && keyAlgsAllowed.length && !sameSet(row.signing_algs, keyAlgsAllowed))
      onChange({ signing_algs: keyAlgsAllowed });
  });

  // Registry: a select of the configured scope sources, plus "Other…".
  const controllers = Array.from(
    new Map(
      catalogue
        .filter((s) => s.kind === "scopes" && s.data_controller)
        .map((s) => [s.data_controller!, s.label] as const),
    ),
  );
  const [otherController, setOtherController] = useState(false);
  const dc = row.data_controller.trim();
  const isOtherController =
    otherController || (dc !== "" && !controllers.some(([id]) => id === dc));

  // Scopes: catalogue choices when the registry's sources were read; free text
  // when there is no source or one failed (its error shown).
  const scopeSources = catalogue.filter((s) => s.kind === "scopes" && s.data_controller === dc);
  const scopeFailed = scopeSources.filter((s) => s.error);
  const scopeItems = uniqueItems(scopeSources);
  const pickControllerFirst = controllers.length > 0 && !isOtherController && dc === "";
  const scopesFree = !pickControllerFirst && (scopeSources.length === 0 || scopeFailed.length > 0);

  // Use case: a select of the catalogue's use cases, plus "Other…"; free text
  // when no source is configured or one failed.
  const ucSources = catalogue.filter((s) => s.kind === "use_cases");
  const ucFailed = ucSources.filter((s) => s.error);
  const ucItems = uniqueItems(ucSources);
  const [otherUseCase, setOtherUseCase] = useState(false);
  const uc = row.use_case.trim();
  const ucItem = ucItems.find((i) => i.id === uc);
  const isOtherUseCase = otherUseCase || (uc !== "" && !ucItem);
  const ucSelect = ucItems.length > 0 && !lockKey;

  // Purposes (registry policies only: granting a use case grants its purpose) and
  // subject ID types; then validity, fetch and partner-signed consents. For a use
  // case the limits only narrow what the use case already defines, so they are
  // folded into "Optional limits" (open when any is set).
  const subjectIdTypesField = (
    <CodeListField
      label="Subject ID types"
      value={row.subject_id_types}
      source={catalogue.find((s) => s.kind === "subject_id_types")}
      onChange={(v) => onChange({ subject_id_types: v })}
    />
  );
  const purposeFields = (
    <div className="grid grid-cols-2 gap-4">
      <CodeListField
        label="Purposes"
        value={row.purposes}
        source={catalogue.find((s) => s.kind === "purposes")}
        onChange={(v) => onChange({ purposes: v })}
      />
      {subjectIdTypesField}
    </div>
  );
  const limitFields = (
    <>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="field-label">Max consent validity</label>
            <input
              className="field-input"
              value={row.max_validity_duration}
              onChange={(e) => onChange({ max_validity_duration: e.target.value })}
              placeholder="ISO-8601, e.g. P1Y (empty = no limit)"
            />
          </div>
          <div>
            <label className="field-label">Data life</label>
            <input
              className="field-input"
              value={row.data_life}
              onChange={(e) => onChange({ data_life: e.target.value })}
              placeholder="ISO-8601, e.g. P30D"
            />
          </div>
          <div>
            <label className="field-label">Fetch type</label>
            <select
              className="field-input"
              value={row.fetch_type}
              onChange={(e) => onChange({ fetch_type: e.target.value })}
            >
              {meta.fetch_types.map((f) => (
                <option key={f} value={f}>
                  {labelOf(f)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label">Max fetch frequency</label>
            <input
              className="field-input"
              value={row.max_fetch_frequency}
              onChange={(e) => onChange({ max_fetch_frequency: e.target.value })}
              placeholder="ISO-8601, e.g. P1D"
            />
          </div>
        </div>
  
        <div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={row.allow_partner_consents}
              onChange={(e) => onChange({ allow_partner_consents: e.target.checked })}
            />
            May present its own signed consents
          </label>
          <p className="text-xs mt-1 text-[color:var(--color-text-muted)]">
            The Consent Manager cannot verify the farmer agreed; only the partner&apos;s signature.
          </p>
        </div>
        <div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={row.allow_assisted_confirmation}
              onChange={(e) => onChange({ allow_assisted_confirmation: e.target.checked })}
            />
            May collect consents by assisted confirmation
          </label>
          <p className="text-xs mt-1 text-[color:var(--color-text-muted)]">
            After the subject&apos;s national-ID login, one &apos;I agree&apos; tick in the partner
            portal instead of a signed form and an approver. The weakest proof.
          </p>
        </div>
    </>
  );
  const hasLimits = Boolean(
    row.subject_id_types.trim() || row.max_validity_duration.trim() ||
      row.data_life.trim() || row.max_fetch_frequency.trim() || row.allow_partner_consents ||
      row.allow_assisted_confirmation || row.fetch_type !== "oneshot",
  );

  return (
    <div className="border border-[color:var(--color-border)] rounded-md p-3 mb-3 space-y-3">
      <div className="flex gap-3">
        <div className="w-48">
          <label className="field-label">Policy for</label>
          <select
            className="field-input"
            value={row.kind}
            disabled={lockKey}
            onChange={(e) => onChange({ kind: e.target.value as PolicyRow["kind"] })}
          >
            <option value="registry">Registry</option>
            <option value="use_case">Use case</option>
          </select>
        </div>
        <div className="flex-1">
          {isRegistry ? (
            <>
              <label className="field-label">Registry (data controller) *</label>
              {controllers.length > 0 && !lockKey && (
                <select
                  className="field-input"
                  value={isOtherController ? OTHER : dc}
                  onChange={(e) => {
                    const v = e.target.value;
                    setOtherController(v === OTHER);
                    onChange({ data_controller: v === OTHER ? "" : v, scopes: "" });
                  }}
                >
                  <option value="">Select a registry…</option>
                  {controllers.map(([id, label]) => (
                    <option key={id} value={id}>
                      {label === id ? id : `${label} (${id})`}
                    </option>
                  ))}
                  <option value={OTHER}>Other…</option>
                </select>
              )}
              {(controllers.length === 0 || lockKey || isOtherController) && (
                <input
                  className={`field-input${controllers.length > 0 && !lockKey ? " mt-2" : ""}`}
                  value={row.data_controller}
                  disabled={lockKey}
                  onChange={(e) => onChange({ data_controller: e.target.value })}
                  placeholder="e.g. farmer_registry"
                />
              )}
            </>
          ) : (
            <>
              <label className="field-label">Use case *</label>
              {ucSelect && (
                <select
                  className="field-input"
                  value={isOtherUseCase ? OTHER : uc}
                  onChange={(e) => {
                    const v = e.target.value;
                    setOtherUseCase(v === OTHER);
                    onChange({ use_case: v === OTHER ? "" : v });
                  }}
                >
                  <option value="">Select a use case…</option>
                  {ucItems.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.label && i.label !== i.id ? `${i.label} (${i.id})` : i.id}
                    </option>
                  ))}
                  <option value={OTHER}>Other…</option>
                </select>
              )}
              {(!ucSelect || isOtherUseCase) && (
                <input
                  className={`field-input${ucSelect ? " mt-2" : ""}`}
                  value={row.use_case}
                  disabled={lockKey}
                  onChange={(e) => onChange({ use_case: e.target.value })}
                  placeholder="name@major, e.g. loan-profile@1"
                />
              )}
            </>
          )}
        </div>
        {onRemove && (
          <button type="button" className="btn-secondary self-end" onClick={onRemove}>
            Remove
          </button>
        )}
      </div>

      {isRegistry ? (
        <div>
          <label className="field-label">Allowed scopes *</label>
          {pickControllerFirst && <p className={muted}>Select a registry to see its scopes.</p>}
          {scopeItems.length > 0 && (
            <CatalogueChoices
              items={scopeItems}
              selected={splitList(row.scopes)}
              showUnlisted={!scopesFree}
              onChange={(ids) => onChange({ scopes: ids.join(", ") })}
            />
          )}
          {scopeSources.length > 0 && !scopesFree && scopeItems.length === 0 && (
            <p className={muted}>{scopeSources.map((s) => s.label).join(", ")} lists none.</p>
          )}
          {scopeFailed.map((s) => (
            <p key={s.label} className={danger}>
              {s.label}: {s.error}. Enter IDs by hand; the request will carry a warning.
            </p>
          ))}
          {scopesFree && (
            <>
              <input
                className={`field-input${scopeItems.length ? " mt-2" : ""}`}
                value={row.scopes}
                onChange={(e) => onChange({ scopes: e.target.value })}
                placeholder="e.g. farmer.basic, farmer.land"
              />
              <p className="text-xs mt-1 text-[color:var(--color-text-muted)]">
                Comma-separated. Scopes the registry defines.
              </p>
            </>
          )}
        </div>
      ) : (
        (ucItem || ucFailed.length > 0 || (isOtherUseCase && uc && ucSources.length > 0)) && (
          <div className="space-y-1">
            {ucItem && (
              <div className={muted}>
                {ucItem.description && <span className="block">{ucItem.description}</span>}
                {ucItem.purpose && (
                  <span className="block">Granting it grants its purpose: {ucItem.purpose}</span>
                )}
              </div>
            )}
            {ucFailed.map((s) => (
              <p key={s.label} className={danger}>
                {s.label}: {s.error}. Enter the use case by hand; the request will carry a
                warning.
              </p>
            ))}
            {isOtherUseCase && uc && ucSources.length > 0 && ucFailed.length === 0 && (
              <p className={danger}>Not in the catalogue: the request will be refused.</p>
            )}
          </div>
        )
      )}

      {isRegistry && purposeFields}

      <div>
        <label className="field-label">Signing algorithms *</label>
        <div className="flex gap-4">
          {meta.signing_algorithms.map((a) => (
            <label key={a} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={row.signing_algs.includes(a)}
                onChange={(e) =>
                  onChange({
                    algs_from_keys: false,
                    signing_algs: e.target.checked
                      ? [...row.signing_algs, a]
                      : row.signing_algs.filter((x) => x !== a),
                  })
                }
              />
              {a}
              {keyAlgs?.length && !keyAlgs.includes(a) ? (
                <span className="text-[color:var(--color-text-muted)]">(no key)</span>
              ) : null}
            </label>
          ))}
        </div>
        {keyAlgs !== undefined && (
          <p className="text-xs mt-1 text-[color:var(--color-text-muted)]">
            {keyAlgs.length
              ? `The partner's keys: ${keyAlgs.join(", ")}. An algorithm with no key is accepted with a warning.`
              : "No keys to match yet."}
          </p>
        )}
      </div>

      {isRegistry ? (
        limitFields
      ) : (
        <details open={hasLimits} className="rounded-md border border-[color:var(--color-border)] p-3">
          <summary className="cursor-pointer text-sm font-medium">Optional limits</summary>
          <p className={`${muted} mt-2 mb-3`}>
            Granting the use case grants its purpose. Leave these empty for no further limit; set
            them only to narrow what this partner may do with the use case.
          </p>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-4">{subjectIdTypesField}</div>
            {limitFields}
          </div>
        </details>
      )}

      {problem && <p className="text-xs text-[color:var(--color-danger)]">{problem}</p>}
    </div>
  );
}

// Read-only summary of one policy (request detail, partner detail). The key
// (registry / use case) is shown by the caller.
export function PolicySummary({ policy }: { policy: PolicyInput }) {
  const muted = "text-[color:var(--color-text-muted)]";
  const list = (v: string[]) => (v.length ? v.join(", ") : "any");
  return (
    <div className="text-sm space-y-1">
      {policy.data_controller && (
        <div>
          <span className={muted}>Scopes: </span>
          {policy.allowed_data_scopes.join(", ") || "—"}
        </div>
      )}
      <div>
        {policy.data_controller && (
          <>
            <span className={muted}>Purposes: </span>
            {list(policy.allowed_purposes)}
            <span className={muted}> · </span>
          </>
        )}
        <span className={muted}>Subject ID types: </span>
        {list(policy.allowed_subject_id_types)}
      </div>
      <div>
        <span className={muted}>Algorithms: </span>
        {policy.allowed_signing_algs.join(", ") || "—"}
        <span className={muted}> · Max validity: </span>
        {policy.max_validity_duration || "no limit"}
      </div>
      <div>
        <span className={muted}>Fetch: </span>
        {labelOf(policy.fetch_type)}
        {policy.max_fetch_frequency ? ` (at most every ${policy.max_fetch_frequency})` : ""}
        <span className={muted}> · Data life: </span>
        {policy.data_life || "—"}
      </div>
      <div>
        <span className={muted}>Own signed consents: </span>
        {policy.allow_partner_consents ? "accepted" : "not accepted"}
      </div>
      <div>
        <span className={muted}>Assisted confirmation: </span>
        {policy.allow_assisted_confirmation ? "allowed" : "not allowed"}
      </div>
    </div>
  );
}
