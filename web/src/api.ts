export type OpportunityKind = "CAMPAIGN" | "POSTING";
export type Eligibility = "PASS" | "FAIL" | "UNKNOWN";
export type EvidenceFit = "PRIMARY" | "APPLY" | "STRETCH" | "LOW" | "UNKNOWN";
export type Trust =
  | "VERIFIED"
  | "VERIFIED_WITH_CONFLICT"
  | "CONSISTENT"
  | "CONFLICTED"
  | "STALE"
  | "UNKNOWN";
export type VerificationResult =
  "OPEN" | "CLOSED" | "NOT_FOUND" | "BLOCKED" | "UNKNOWN";
export type ReviewDecision =
  "UNDECIDED" | "PREPARE_APPLY" | "VERIFY_FIRST" | "HOLD" | "REJECT";
export type ApplicationStage =
  | "TO_APPLY"
  | "APPLIED"
  | "ASSESSMENT"
  | "INTERVIEW"
  | "OFFER"
  | "REJECTED"
  | "WITHDRAWN";

export interface Opportunity {
  id: string;
  kind: OpportunityKind;
  company: string;
  title: string;
  source_title?: string;
  title_inferred?: boolean;
  title_inference_reason?: string;
  official_job_id: string | null;
  candidate_domain: string;
  official_domain: string;
  official_scope_path: string;
  official_domain_verified: boolean;
  review_status: string;
  cities: string[];
  graduation_years: string[];
  recruitment_type: string;
  industry?: string;
  employer_type?: string;
  written_test?: string;
  published_at?: string;
  deadline: string;
  apply_url: string;
  source_count: number;
  observation_count?: number;
  historical_difference_count?: number;
  conflict_count: number;
  verification: VerificationResult | null;
  eligibility: Eligibility | null;
  evidence_fit: EvidenceFit | null;
  trust: Trust | null;
  decision_current: boolean;
  needs_recompute: boolean;
  manual_decision: ReviewDecision;
  unknowns: DecisionUnknown[];
  updated_at: string;
}

export interface PaginatedOpportunities {
  items: Opportunity[];
  total: number;
  page: number;
  page_size: number;
}

export interface DashboardSummary {
  opportunity_count: number;
  posting_count: number;
  campaign_count: number;
  shortlist_total_count: number;
  shortlist_ready_count: number;
  ready_count: number;
  verify_first_count: number;
  unresolved_conflict_count: number;
  latest_import_at: string | null;
  independent_source_count: number;
  today_goal: number;
}

export interface RuntimeMeta {
  environment: string;
  read_only: boolean;
  data_mode: "synthetic-demo" | "local-workspace";
  label: string;
}

export interface EvaluationSummary {
  schema_version: string;
  harness_version: string;
  generated_at: string;
  methodology: {
    contract_definition: string;
    database_policy: string;
    fixture_data_class: string;
    heuristic_sample_definition: string;
    outcome_claim_policy: string;
  };
  fixture_summary: Record<
    "contract_boundary" | "heuristic_sample",
    {
      exact_match_rate_on_fixture_set: number;
      failed: number;
      passed: number;
      total: number;
    }
  >;
  database_quality: {
    database_label: string;
    privacy_mode: string;
    distributions: {
      raw_parse_status: Record<string, number>;
      opportunity_kind: Record<string, number>;
    };
    structural_checks: {
      active_selected_claim_duplicate_groups: number;
      current_decision_duplicate_groups: number;
      opportunities_with_origin: number;
      opportunities_without_origin: number;
      opportunity_origin_coverage: number;
      raw_materialization_coverage: number;
      raw_records_with_origin: number;
      raw_records_without_origin: number;
    };
    table_counts: {
      raw_records: number;
      opportunities: number;
      field_claims: number;
      sources: number;
      [key: string]: number;
    };
  };
  api_performance: {
    measurement_scope: string;
    is_production_slo: boolean;
    endpoints: Array<{
      endpoint: string;
      http_statuses: number[];
      latency_ms: {
        min: number;
        median: number;
        p95: number;
        max: number;
      };
      sample_count: number;
      status: string;
    }>;
  };
  limitations: string[];
}

export interface Claim {
  id: string;
  field_name: string;
  raw_value: string;
  normalized_value: unknown;
  authority: number;
  observed_at: string;
  evidence_label: string;
  evidence_url: string;
  selected: boolean;
  applicable: boolean;
  resolution_reason: string;
  source_name: string;
}

export interface Verification {
  id: string;
  result: VerificationResult;
  evidence_scope: OpportunityKind | "UNKNOWN";
  verified_domain: string;
  verified_scope_path: string;
  url: string;
  final_url: string;
  checked_at: string;
  evidence_excerpt: string;
  extracted_fields: Record<string, unknown>;
  reviewer: string;
}

export interface DecisionReason {
  axis?: "eligibility" | "evidence_fit" | "trust";
  code: string;
  field: string;
  message: string;
  evidence_refs?: string[];
}

export interface DecisionUnknown {
  axis?: "eligibility" | "evidence_fit" | "trust";
  code: string;
  field: string;
  message: string;
}

export interface Decision {
  id: string;
  eligibility: Eligibility;
  evidence_fit: EvidenceFit;
  trust: Trust;
  reasons: DecisionReason[];
  unknowns: DecisionUnknown[];
  evidence_links: Array<{
    fact_id: string;
    value: string;
    evidence_text: string;
    start: number;
    end: number;
  }>;
  rule_version: string;
  is_current: boolean;
  manual_decision: ReviewDecision;
  override_reason: string;
  created_at: string;
}

export interface OpportunityDetail {
  item: Opportunity;
  claims: Claim[];
  origins: Array<{
    raw_record_id: string;
    source_name: string;
    batch_id: string;
    file_name: string;
    row_number: number;
    raw_payload: Record<string, unknown>;
    canonical_payload: Record<string, unknown>;
  }>;
  verifications: Verification[];
  decision_history: Decision[];
  linked_campaigns: string[];
  linked_postings: string[];
}

export interface SourceSummary {
  id: string;
  name: string;
  kind: string;
  independence_group: string;
  description: string;
  batch_count: number;
  raw_record_count: number;
  latest_import_at: string | null;
  connector_type: string | null;
  connector_status: string | null;
  connector_schedule: string | null;
  connector_last_sync_at: string | null;
}

export interface BatchSummary {
  id: string;
  source_id: string;
  file_name: string;
  file_format: string;
  row_count: number;
  success_count: number;
  error_count: number;
  snapshot_at: string | null;
  imported_at: string;
}

export interface FeishuPreview {
  app_token: string;
  table_id: string;
  view_id: string;
  page_count: number;
  field_count: number;
  fetched_at: string;
  preview: ImportPreview;
}

export interface RemoteConnector {
  source_id: string;
  source_name: string;
  connector_type: string;
  source_url: string;
  table_id: string;
  view_id: string;
  schedule: string;
  enabled: boolean;
  last_sync_at: string | null;
  last_success_at: string | null;
  last_status: string;
  last_error: string;
}

export interface SourceSyncRun {
  id: string;
  source_id: string;
  status: string;
  batch_id: string | null;
  row_count: number;
  field_count: number;
  added_count: number;
  modified_count: number;
  missing_count: number;
  unchanged_count: number;
  error: string;
  started_at: string;
  finished_at: string | null;
}

export interface RemoteSyncResponse {
  status: string;
  source_id: string;
  batch_id: string;
  row_count: number;
  field_count: number;
  added_count: number;
  modified_count: number;
  missing_count: number;
  unchanged_count: number;
  materialized_count: number;
}

export interface ProfileFact {
  id: string;
  resume_document_id?: string | null;
  category: string;
  label: string;
  value: string;
  evidence_text: string;
  evidence_start: number | null;
  evidence_end: number | null;
  provenance: string;
  confirmed: boolean;
}

export interface ResumeDocument {
  id: string;
  name: string;
  source_format: string;
  content_hash: string;
  is_active: boolean;
  created_at: string;
  fact_count: number;
}

export interface Preference {
  key: string;
  value: unknown;
  hard_constraint: boolean;
  confirmed: boolean;
}

export interface Profile {
  active_resume_id?: string | null;
  resumes?: ResumeDocument[];
  facts: ProfileFact[];
  preferences: Preference[];
}

export interface ShortlistEntry {
  priority: number;
  note: string;
  added_at: string;
  application_stage: ApplicationStage;
  next_action: string;
  next_action_at: string | null;
  applied_at: string | null;
  updated_at: string;
  ready: boolean;
  blockers: string[];
  opportunity: Opportunity;
}

export interface ImportPreviewRow {
  row_number: number;
  canonical: {
    company?: string;
    title?: string;
    cities?: string[];
    graduation_years?: string[];
    recruitment_type?: string;
    [key: string]: unknown;
  };
  kind: {
    kind: "CAMPAIGN" | "POSTING" | "NON_JOB";
    confidence: number;
    reasons: string[];
    needs_review: boolean;
  };
  parse_status: string;
  errors: string[];
}

export interface ImportPreview {
  file_name: string;
  file_format: string;
  file_hash: string;
  header: string[];
  mapping: Record<string, string>;
  mapping_version: string;
  row_count: number;
  success_count: number;
  error_count: number;
  kind_counts: { CAMPAIGN: number; POSTING: number; NON_JOB: number };
  sample_rows: ImportPreviewRow[];
  rejected_rows: Array<Record<string, unknown>>;
}

export interface DuplicateCandidate {
  id: string;
  score: number;
  features: Record<string, unknown>;
  decision: string;
  decision_reason: string;
  left: {
    id: string;
    kind: string;
    title: string;
    official_job_id: string | null;
  } | null;
  right: {
    id: string;
    kind: string;
    title: string;
    official_job_id: string | null;
  } | null;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  if (import.meta.env.VITE_STATIC_DEMO === "true") {
    return staticDemoApi<T>(path, options);
  }
  const headers = new Headers(options?.headers);
  if (
    options?.body &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload.detail) message = formatApiDetail(payload.detail);
    } catch {
      // Keep the HTTP fallback when the server does not return JSON.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function formatApiDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== "object") return String(item);
        const value = item as { msg?: unknown; loc?: unknown };
        const location = Array.isArray(value.loc)
          ? value.loc.slice(1).join(".")
          : "";
        const text = typeof value.msg === "string" ? value.msg : "参数无效";
        return location ? `${location}：${text}` : text;
      })
      .filter(Boolean);
    return messages.join("；") || "提交内容未通过校验";
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return String(detail);
}

export function queryString(
  values: Record<string, string | number | undefined>,
) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return params.toString();
}

export function humanDate(value?: string | null, includeTime = false) {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

export function displayValue(value: unknown) {
  if (Array.isArray(value)) return value.join("、") || "—";
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

export function isConfirmedOfficialLink(item: Opportunity): boolean {
  if (
    item.kind !== "POSTING" ||
    !item.official_domain_verified ||
    !item.official_domain ||
    !item.official_job_id ||
    !item.apply_url
  )
    return false;
  try {
    const host = new URL(item.apply_url).hostname
      .toLowerCase()
      .replace(/^www\./, "");
    const domain = item.official_domain.toLowerCase().replace(/^www\./, "");
    if (host !== domain && !host.endsWith(`.${domain}`)) return false;
    if (!item.official_scope_path) return true;
    const path = new URL(item.apply_url).pathname
      .toLowerCase()
      .replace(/\/$/, "");
    const scope = item.official_scope_path.toLowerCase().replace(/\/$/, "");
    return path === scope || path.startsWith(`${scope}/`);
  } catch {
    return false;
  }
}
import { staticDemoApi } from "./staticDemo";
