from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl

from campus_job_desk.domain.enums import (
    ApplicationStage,
    DuplicateDecision,
    Eligibility,
    EvidenceFit,
    OpportunityKind,
    ReviewDecision,
    SourceKind,
    Trust,
    VerificationResult,
)


class ImportResponse(BaseModel):
    status: str
    batch_id: str
    source_id: str
    row_count: int
    success_count: int
    error_count: int
    materialized_count: int = 0


class SourceSummary(BaseModel):
    id: str
    name: str
    kind: str
    independence_group: str
    description: str
    batch_count: int
    raw_record_count: int
    latest_import_at: Optional[datetime] = None
    connector_type: Optional[str] = None
    connector_status: Optional[str] = None
    connector_schedule: Optional[str] = None
    connector_last_sync_at: Optional[datetime] = None


class BatchSummary(BaseModel):
    id: str
    source_id: str
    file_name: str
    file_format: str
    row_count: int
    success_count: int
    error_count: int
    snapshot_at: Optional[datetime] = None
    imported_at: datetime


class FeishuPreviewCreate(BaseModel):
    source_url: str = Field(min_length=10, max_length=4000)
    source_name: str = Field(min_length=1, max_length=160)
    source_kind: SourceKind = SourceKind.PAID_TABLE
    mapping: dict[str, str] = Field(default_factory=dict)


class FeishuConnectorCreate(FeishuPreviewCreate):
    source_id: str = Field(min_length=2, max_length=64)
    independence_group: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    schedule: str = Field(default="DAILY", pattern="^(DAILY|MANUAL)$")


class FeishuPreviewResponse(BaseModel):
    app_token: str
    table_id: str
    view_id: str
    page_count: int
    field_count: int
    fetched_at: datetime
    preview: dict[str, Any]


class RemoteConnectorView(BaseModel):
    source_id: str
    source_name: str
    connector_type: str
    source_url: str
    table_id: str
    view_id: str
    schedule: str
    enabled: bool
    last_sync_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_status: str
    last_error: str


class SourceSyncRunView(BaseModel):
    id: str
    source_id: str
    status: str
    batch_id: Optional[str] = None
    row_count: int
    field_count: int
    added_count: int
    modified_count: int
    missing_count: int
    unchanged_count: int
    error: str
    started_at: datetime
    finished_at: Optional[datetime] = None


class SourceSyncChangeView(BaseModel):
    id: str
    sync_run_id: str
    source_record_id: str
    change_type: str
    previous_hash: str
    current_hash: str


class RemoteSyncResponse(BaseModel):
    status: str
    source_id: str
    batch_id: str
    row_count: int
    field_count: int
    added_count: int
    modified_count: int
    missing_count: int
    unchanged_count: int
    materialized_count: int


class OpportunityListItem(BaseModel):
    id: str
    kind: OpportunityKind
    company: str
    title: str
    source_title: str = ""
    title_inferred: bool = False
    title_inference_reason: str = ""
    official_job_id: Optional[str] = None
    candidate_domain: str = ""
    official_domain: str = ""
    official_scope_path: str = ""
    official_domain_verified: bool = False
    review_status: str
    cities: list[str] = Field(default_factory=list)
    graduation_years: list[str] = Field(default_factory=list)
    recruitment_type: str = ""
    industry: str = ""
    employer_type: str = ""
    written_test: str = ""
    published_at: str = ""
    deadline: str = ""
    apply_url: str = ""
    source_count: int = 0
    observation_count: int = 0
    conflict_count: int = 0
    historical_difference_count: int = 0
    verification: Optional[VerificationResult] = None
    eligibility: Optional[Eligibility] = None
    evidence_fit: Optional[EvidenceFit] = None
    trust: Optional[Trust] = None
    decision_current: bool = False
    needs_recompute: bool = False
    manual_decision: ReviewDecision = ReviewDecision.UNDECIDED
    unknowns: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime


class PaginatedOpportunities(BaseModel):
    items: list[OpportunityListItem]
    total: int
    page: int
    page_size: int


class ClaimView(BaseModel):
    id: str
    field_name: str
    raw_value: str
    normalized_value: Any
    authority: int
    observed_at: datetime
    evidence_label: str
    evidence_url: str
    selected: bool
    applicable: bool
    resolution_reason: str
    source_name: str = ""


class VerificationView(BaseModel):
    id: str
    result: VerificationResult
    evidence_scope: str
    verified_domain: str
    verified_scope_path: str = ""
    url: str
    final_url: str
    checked_at: datetime
    evidence_excerpt: str
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    reviewer: str


class DecisionView(BaseModel):
    id: str
    eligibility: Eligibility
    evidence_fit: EvidenceFit
    trust: Trust
    reasons: list[dict[str, Any]]
    unknowns: list[dict[str, Any]]
    evidence_links: list[dict[str, Any]]
    rule_version: str
    is_current: bool
    manual_decision: ReviewDecision
    override_reason: str
    created_at: datetime


class OriginView(BaseModel):
    raw_record_id: str
    source_name: str
    batch_id: str
    file_name: str
    row_number: int
    raw_payload: dict[str, Any]
    canonical_payload: dict[str, Any]


class OpportunityDetail(BaseModel):
    item: OpportunityListItem
    claims: list[ClaimView]
    origins: list[OriginView]
    verifications: list[VerificationView]
    decision_history: list[DecisionView]
    linked_campaigns: list[str] = Field(default_factory=list)
    linked_postings: list[str] = Field(default_factory=list)


class VerificationCreate(BaseModel):
    result: VerificationResult
    url: HttpUrl
    final_url: Optional[HttpUrl] = None
    checked_at: Optional[datetime] = None
    evidence_excerpt: str = Field(default="", max_length=4000)
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    reviewer: str = Field(default="user", max_length=100)


class ManualDecisionUpdate(BaseModel):
    decision: ReviewDecision
    reason: str = Field(default="", max_length=2000)


class DuplicateReviewUpdate(BaseModel):
    decision: DuplicateDecision
    reason: str = Field(min_length=2, max_length=2000)


class CampaignPostingCreate(BaseModel):
    posting_id: str
    evidence: str = Field(min_length=2, max_length=2000)
    confidence: float = Field(default=1.0, ge=0, le=1)


class ClassificationUpdate(BaseModel):
    kind: OpportunityKind
    reason: str = Field(min_length=4, max_length=2000)


class OfficialDomainUpdate(BaseModel):
    domain: str = Field(min_length=3, max_length=500)
    reason: str = Field(min_length=4, max_length=2000)


class OfficialIdentityUpdate(BaseModel):
    official_job_id: str = Field(min_length=2, max_length=255)
    url: HttpUrl
    reason: str = Field(min_length=4, max_length=2000)


class ShortlistCreate(BaseModel):
    priority: int = Field(default=0, ge=0, le=100)
    note: str = Field(default="", max_length=2000)


class ApplicationProgressUpdate(BaseModel):
    stage: ApplicationStage
    next_action: str = Field(default="", max_length=500)
    next_action_at: Optional[datetime] = None


class PreferenceUpsert(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: Any
    hard_constraint: bool = False
    confirmed: bool = True


class ProfileTextCreate(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    source_name: str = Field(default="resume.txt", max_length=255)


class ProfileFactUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=255)
    value: Optional[str] = None
    confirmed: Optional[bool] = None


class DashboardSummary(BaseModel):
    opportunity_count: int
    posting_count: int
    campaign_count: int
    shortlist_total_count: int
    shortlist_ready_count: int
    ready_count: int
    verify_first_count: int
    unresolved_conflict_count: int
    latest_import_at: Optional[datetime] = None
    independent_source_count: int
    today_goal: int = 5


class DemoSeedRequest(BaseModel):
    reset_derived: bool = False
    source_kind: SourceKind = SourceKind.SYNTHETIC


class DecisionRecomputeRequest(BaseModel):
    opportunity_ids: Optional[list[str]] = None
