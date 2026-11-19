"use client";

import { useEffect, useState } from "react";
import { api } from "./api";

// Choices for policy forms, from the backend's GET /catalogue: registries' data
// scopes (data_controller set), exchanges' use cases, and the Master Data code
// lists for purposes and subject ID types. A source the backend could not read
// has `error` set and no items; a Master Data list the country does not have
// has `note` set. Either way the form falls back to free text, as it does when
// no source is configured.
export interface CatalogueItem {
  id: string;
  label?: string | null;
  description?: string | null;
  purpose?: string | null; // use cases
  fields?: string[]; // scopes
}

export interface CatalogueSource {
  kind: "scopes" | "use_cases" | "purposes" | "subject_id_types";
  data_controller?: string | null;
  label: string;
  items: CatalogueItem[];
  error?: string | null;
  note?: string | null;
}

let cached: Promise<CatalogueSource[]> | null = null;

export function useCatalogue(): CatalogueSource[] {
  const [sources, setSources] = useState<CatalogueSource[]>([]);
  useEffect(() => {
    if (!cached) {
      cached = api
        .get<{ sources: CatalogueSource[] }>("/catalogue")
        .then((d) => {
          if (d.sources.some((s) => s.error)) cached = null; // retry the failed source next time
          return d.sources;
        })
        .catch(() => {
          cached = null; // retry on next mount
          return [];
        });
    }
    let alive = true;
    cached.then((s) => alive && setSources(s));
    return () => {
      alive = false;
    };
  }, []);
  return sources;
}
