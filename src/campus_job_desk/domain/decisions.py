from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .enums import Eligibility, EvidenceFit, OpportunityKind, Trust, VerificationResult
from .schemas import CanonicalRecord


class DecisionReason(BaseModel):
    code: str
    field: str
    message: str
    evidence_refs: list[str] = Field(default_factory=list)


class DecisionUnknown(BaseModel):
    code: str
    field: str
    message: str


class EligibilityDecision(BaseModel):
    version: str = "eligibility.v1"
    result: Eligibility
    reasons: list[DecisionReason] = Field(default_factory=list)
    unknowns: list[DecisionUnknown] = Field(default_factory=list)


class EvidenceFitDecision(BaseModel):
    version: str = "evidence-fit.v1"
    result: EvidenceFit
    reasons: list[DecisionReason] = Field(default_factory=list)
    unknowns: list[DecisionUnknown] = Field(default_factory=list)


class TrustDecision(BaseModel):
    version: str = "trust.v1"
    result: Trust
    reasons: list[DecisionReason] = Field(default_factory=list)
    unknowns: list[DecisionUnknown] = Field(default_factory=list)


class JobDecisionContext(BaseModel):
    record: CanonicalRecord
    opportunity_kind: OpportunityKind
    verification_result: VerificationResult = VerificationResult.UNKNOWN
    source_count: int = Field(default=0, ge=0)
    official_specific_posting: bool = False
    official_checked_at: Optional[datetime] = None
    latest_source_at: Optional[datetime] = None
    conflicting_fields: list[str] = Field(default_factory=list)
    jd_text: str = ""


class DecisionBundle(BaseModel):
    version: str = "decision-bundle.v1"
    generated_at: datetime
    eligibility: EligibilityDecision
    evidence_fit: EvidenceFitDecision
    trust: TrustDecision
