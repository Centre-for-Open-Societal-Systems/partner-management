"use client";

import { useEffect, useState } from "react";
import { api } from "./api";

// Allowed values for every enum-backed field, served by the backend's
// GET /metadata (built from the API's model enums + crypto_allowed_algorithms),
// so selects offer exactly what the API accepts. FALLBACK mirrors the backend
// defaults and is only used until /metadata answers (or if it fails).
export interface Metadata {
  algorithms: string[];
  partner_statuses: string[];
  key_statuses: string[];
  request_types: string[];
  request_statuses: string[];
  // Algorithms a policy may allow; policy fetch types and version statuses.
  signing_algorithms: string[];
  fetch_types: string[];
  policy_statuses: string[];
  identifier_pattern: string;
  identifier_hint: string;
}

export const FALLBACK_METADATA: Metadata = {
  algorithms: ["RS256", "ES256", "EdDSA"],
  partner_statuses: ["created", "active", "disabled"],
  key_statuses: ["pending", "active", "revoked"],
  request_types: ["onboarding", "key_update", "policy"],
  request_statuses: ["created", "approved", "rejected"],
  signing_algorithms: ["RS256", "ES256", "EdDSA"],
  fetch_types: ["oneshot", "periodic"],
  policy_statuses: ["pending", "active", "superseded", "rejected", "revoked"],
  identifier_pattern: "^[^\\s/?#%]+$",
  identifier_hint: "No spaces or '/', '?', '#', '%' (e.g. PARTNER_G2P_BRIDGE).",
};

const LABELS: Record<string, string> = {
  onboarding: "Onboarding",
  key_update: "Key update",
  policy: "Policy",
  oneshot: "One-shot",
  periodic: "Periodic",
};

export function labelOf(value: string): string {
  return LABELS[value] ?? value;
}

let cached: Promise<Metadata> | null = null;

export function useMetadata(): Metadata {
  const [meta, setMeta] = useState<Metadata>(FALLBACK_METADATA);
  useEffect(() => {
    if (!cached) {
      cached = api.get<Metadata>("/metadata").catch(() => {
        cached = null; // retry on next mount
        return FALLBACK_METADATA;
      });
    }
    let alive = true;
    cached.then((m) => alive && setMeta(m));
    return () => {
      alive = false;
    };
  }, []);
  return meta;
}

export function matchesIdentifier(meta: Metadata, value: string): boolean {
  try {
    return new RegExp(meta.identifier_pattern).test(value);
  } catch {
    return true; // never block on a pattern the browser cannot compile
  }
}
