from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator

from .enums import ProfileFactKind, ResumeFormat


class EvidenceSpan(BaseModel):
    """Zero-based, half-open character offsets into the original resume text."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "EvidenceSpan":
        if self.end <= self.start:
            raise ValueError("evidence span end must be greater than start")
        return self


class FactProvenance(BaseModel):
    source_type: str = "resume"
    source_name: str
    extraction_method: str


class ProfileFact(BaseModel):
    fact_id: str
    kind: ProfileFactKind
    value: str
    evidence_text: str
    span: EvidenceSpan
    provenance: FactProvenance
    confirmed: bool = False

    @model_validator(mode="after")
    def evidence_length_must_match_span(self) -> "ProfileFact":
        if self.span.end - self.span.start != len(self.evidence_text):
            raise ValueError("evidence_text length must match its half-open span")
        return self


class JobPreferences(BaseModel):
    """User choices only. Education and graduation year belong to facts."""

    accepted_cities: list[str] = Field(default_factory=list)
    accepted_recruitment_types: list[str] = Field(default_factory=list)
    target_role_keywords: list[str] = Field(default_factory=list)
    excluded_work_patterns: list[str] = Field(default_factory=list)


class EvidenceProfile(BaseModel):
    schema_version: str = "evidence-profile.v1"
    source_name: str
    source_format: ResumeFormat
    raw_text: str
    facts: list[ProfileFact] = Field(default_factory=list)
    preferences: JobPreferences = Field(default_factory=JobPreferences)
    parser_warnings: list[str] = Field(default_factory=list)

    def confirmed_facts(self, kind: Optional[ProfileFactKind] = None) -> list[ProfileFact]:
        return [
            fact
            for fact in self.facts
            if fact.confirmed and (kind is None or fact.kind is kind)
        ]
