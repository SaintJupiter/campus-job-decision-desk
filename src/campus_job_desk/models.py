from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    independence_group: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    batches: Mapped[list["ImportBatch"]] = relationship(back_populates="source")
    remote_connector: Mapped[Optional["RemoteSourceConnector"]] = relationship(
        back_populates="source", uselist=False
    )


class RemoteSourceConnector(Base):
    """A refreshable source definition. Credentials intentionally never live here."""

    __tablename__ = "remote_source_connectors"

    source_id: Mapped[str] = mapped_column(
        ForeignKey("data_sources.id"), primary_key=True
    )
    connector_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    app_token: Mapped[str] = mapped_column(String(255), nullable=False)
    table_id: Mapped[str] = mapped_column(String(255), nullable=False)
    view_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    mapping_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    mapping_version: Mapped[str] = mapped_column(
        String(64), default="canonical-v1", nullable=False
    )
    schedule: Mapped[str] = mapped_column(String(32), default="DAILY", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(String(32), default="NEVER", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    source: Mapped[DataSource] = relationship(back_populates="remote_connector")
    sync_runs: Mapped[list["SourceSyncRun"]] = relationship(back_populates="connector")


class SourceSyncRun(Base):
    __tablename__ = "source_sync_runs"
    __table_args__ = (
        Index("ix_source_sync_runs_source_started", "source_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("remote_source_connectors.source_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_id: Mapped[Optional[str]] = mapped_column(ForeignKey("import_batches.id"))
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    field_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    added_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    modified_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    connector: Mapped[RemoteSourceConnector] = relationship(back_populates="sync_runs")
    changes: Mapped[list["SourceSyncChange"]] = relationship(back_populates="sync_run")


class SourceSyncChange(Base):
    __tablename__ = "source_sync_changes"
    __table_args__ = (
        Index("ix_source_sync_changes_run_type", "sync_run_id", "change_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sync_run_id: Mapped[str] = mapped_column(
        ForeignKey("source_sync_runs.id"), nullable=False
    )
    source_record_id: Mapped[str] = mapped_column(String(255), nullable=False)
    change_type: Mapped[str] = mapped_column(String(24), nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    current_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    sync_run: Mapped[SourceSyncRun] = relationship(back_populates="changes")


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("source_id", "file_hash", name="uq_import_source_hash"),
        Index("ix_import_batches_snapshot_at", "snapshot_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(32), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    mapping_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_json: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    source: Mapped[DataSource] = relationship(back_populates="batches")
    raw_records: Mapped[list["RawRecord"]] = relationship(back_populates="batch")


class RawRecord(Base):
    __tablename__ = "raw_records"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_number", name="uq_raw_batch_row"),
        Index("ix_raw_identity_hint", "identity_hint"),
        Index("ix_raw_row_hash", "row_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_record_id: Mapped[Optional[str]] = mapped_column(String(255))
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_hint: Mapped[Optional[str]] = mapped_column(Text)
    identity_strength: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_is_stable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_payload: Mapped[str] = mapped_column(Text, nullable=False)
    kind_prediction: Mapped[str] = mapped_column(String(24), nullable=False)
    kind_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    kind_reasons: Mapped[str] = mapped_column(Text, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(24), nullable=False)
    parse_errors: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    batch: Mapped[ImportBatch] = relationship(back_populates="raw_records")
    origins: Mapped[list["OpportunityOrigin"]] = relationship(back_populates="raw_record")


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("normalized_name", "official_domain", name="uq_org_name_domain"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_domain: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    official_domain: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    official_scope_path: Mapped[str] = mapped_column(
        String(500), default="", nullable=False
    )
    official_domain_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    official_domain_source: Mapped[str] = mapped_column(
        String(255), default="", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="organization")


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opportunities_kind", "kind"),
        Index("ix_opportunities_canonical_key", "canonical_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[Optional[str]] = mapped_column(ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    display_title: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_key: Mapped[Optional[str]] = mapped_column(Text)
    official_job_id: Mapped[Optional[str]] = mapped_column(String(255))
    review_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    organization: Mapped[Optional[Organization]] = relationship(back_populates="opportunities")
    origins: Mapped[list["OpportunityOrigin"]] = relationship(back_populates="opportunity")
    claims: Mapped[list["FieldClaim"]] = relationship(back_populates="opportunity")
    verifications: Mapped[list["VerificationAttempt"]] = relationship(back_populates="opportunity")


class OpportunityOrigin(Base):
    __tablename__ = "opportunity_origins"

    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), primary_key=True)
    raw_record_id: Mapped[str] = mapped_column(ForeignKey("raw_records.id"), primary_key=True)
    relation: Mapped[str] = mapped_column(String(32), default="OBSERVED_AS", nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    opportunity: Mapped[Opportunity] = relationship(back_populates="origins")
    raw_record: Mapped[RawRecord] = relationship(back_populates="origins")


class FieldClaim(Base):
    __tablename__ = "field_claims"
    __table_args__ = (
        Index("ix_field_claims_opportunity_field", "opportunity_id", "field_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), nullable=False)
    raw_record_id: Mapped[Optional[str]] = mapped_column(ForeignKey("raw_records.id"))
    verification_id: Mapped[Optional[str]] = mapped_column(ForeignKey("verification_attempts.id"))
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    authority: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_label: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parser: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    resolution_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    opportunity: Mapped[Opportunity] = relationship(back_populates="claims")


class CampaignPostingLink(Base):
    __tablename__ = "campaign_posting_links"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), primary_key=True)
    posting_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), primary_key=True)
    relation: Mapped[str] = mapped_column(String(32), default="CONTAINS", nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        UniqueConstraint("left_opportunity_id", "right_opportunity_id", name="uq_duplicate_pair"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    left_opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), nullable=False)
    right_opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    features: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), default="REVIEW", nullable=False)
    decision_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class VerificationAttempt(Base):
    __tablename__ = "verification_attempts"
    __table_args__ = (Index("ix_verification_opportunity_checked", "opportunity_id", "checked_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), nullable=False)
    result: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence_scope: Mapped[str] = mapped_column(
        String(24), default="UNKNOWN", nullable=False
    )
    verified_domain: Mapped[str] = mapped_column(
        String(255), default="", nullable=False
    )
    verified_scope_path: Mapped[str] = mapped_column(
        String(500), default="", nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    extracted_fields: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    reviewer: Mapped[str] = mapped_column(String(100), default="user", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    opportunity: Mapped[Opportunity] = relationship(back_populates="verifications")


class ResumeDocument(Base):
    __tablename__ = "resume_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_format: Mapped[str] = mapped_column(String(24), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    facts: Mapped[list["ProfileFact"]] = relationship(back_populates="resume_document")


class ProfileFact(Base):
    __tablename__ = "profile_facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_document_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("resume_documents.id")
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_start: Mapped[Optional[int]] = mapped_column(Integer)
    evidence_end: Mapped[Optional[int]] = mapped_column(Integer)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    resume_document: Mapped[Optional[ResumeDocument]] = relationship(
        back_populates="facts"
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    hard_constraint: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class DecisionSnapshot(Base):
    __tablename__ = "decision_snapshots"
    __table_args__ = (Index("ix_decisions_opportunity_created", "opportunity_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), nullable=False)
    eligibility: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence_fit: Mapped[str] = mapped_column(String(24), nullable=False)
    trust: Mapped[str] = mapped_column(String(32), nullable=False)
    reasons: Mapped[str] = mapped_column(Text, nullable=False)
    unknowns: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_links: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    manual_decision: Mapped[str] = mapped_column(String(32), default="UNDECIDED", nullable=False)
    override_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DecisionEvent(Base):
    __tablename__ = "decision_events"
    __table_args__ = (Index("ix_decision_events_entity", "entity_type", "entity_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShortlistEntry(Base):
    __tablename__ = "shortlist_entries"

    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    application_stage: Mapped[str] = mapped_column(
        String(32), default="TO_APPLY", nullable=False
    )
    next_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    next_action_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class WorkspaceMetadata(Base):
    __tablename__ = "workspace_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
