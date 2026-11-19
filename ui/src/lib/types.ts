export interface PartnerRequest {
  id: string;
  request_type: "onboarding" | "key_update" | "policy";
  partner_id: string;
  name?: string | null;
  org_name?: string | null;
  description?: string | null;
  jwks_url?: string | null;
  keys_from_jwks_url?: boolean;
  proposed_keys: ProposedKey[];
  revoke_kids: string[];
  proposed_policies: PolicyInput[];
  // Policies revoked on approval, by key.
  revoke: PolicyRef[];
  // Checks that could not run at submission (a catalogue source was unreachable).
  warnings: string[];
  status: "created" | "approved" | "rejected";
  submitted_by?: string | null;
  reviewed_by?: string | null;
  review_notes?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface ProposedKey {
  kid: string;
  algorithm: string;
  public_key?: string;
  key_fingerprint?: string | null;
  not_before?: string | null;
  not_after?: string | null;
}

export interface Partner {
  id: string;
  partner_id: string;
  name: string;
  org_name?: string | null;
  description?: string | null;
  jwks_url?: string | null;
  // Keys read from jwks_url when needed (in addition to the keys listed here).
  keys_from_jwks_url?: boolean;
  status: "created" | "active" | "disabled";
  created_by?: string | null;
  approved_by?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface AuditEvent {
  id: string;
  created_at: string;
  actor_name?: string | null;
  actor_id?: string | null;
  action: string;
  entity_type: string;
  entity_id?: string | null;
  partner_id: string;
  request_id?: string | null;
  details: Record<string, unknown>;
}

export interface PartnerKey {
  id: string;
  partner_id: string;
  kid: string;
  algorithm: string;
  public_key: string;
  key_fingerprint?: string | null;
  status: "pending" | "active" | "revoked";
  not_before?: string | null;
  not_after?: string | null;
  created_at: string;
}

// Names one policy of a partner: exactly one of the two is set.
export interface PolicyRef {
  data_controller?: string | null;
  use_case?: string | null;
}

// What a partner may access, one policy per key: data_controller set = a scope
// policy for that registry (allowed_data_scopes); use_case set (name@major) = a
// policy for that exchange use case.
export interface PolicyInput {
  data_controller: string | null;
  use_case: string | null;
  allowed_data_scopes: string[];
  // Registry (scope) policies only; always empty for a use-case policy.
  allowed_purposes: string[];
  allowed_subject_id_types: string[];
  allowed_signing_algs: string[];
  max_validity_duration: string | null;
  fetch_type: string;
  max_fetch_frequency: string | null;
  data_life: string | null;
  // The partner may present consents it collected and signed itself.
  allow_partner_consents: boolean;
  // The partner may collect consents by assisted confirmation: after the
  // subject's national-ID login, one 'I agree' tick in the partner portal.
  allow_assisted_confirmation: boolean;
}

export interface PartnerPolicy extends PolicyInput {
  id: string;
  partner_id: string;
  version: number;
  status: "pending" | "active" | "superseded" | "rejected" | "revoked";
  request_id: string;
  created_by?: string | null;
  approved_by?: string | null;
  created_at: string;
  effective_from?: string | null;
}
