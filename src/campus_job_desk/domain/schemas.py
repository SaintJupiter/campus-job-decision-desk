from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import IdentityStrength, OpportunityKind, ParseStatus, SourceKind


class CanonicalRecord(BaseModel):
    company: str = ""
    title: str = ""
    cities: list[str] = Field(default_factory=list)
    graduation_years: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    recruitment_type: str = ""
    industry: str = ""
    employer_type: str = ""
    written_test: str = ""
    published_at: str = ""
    deadline: str = ""
    announcement_url: str = ""
    apply_url: str = ""
    official_job_id: Optional[str] = None
    source_record_id: Optional[str] = None
    notes: str = ""


class IdentityHint(BaseModel):
    value: Optional[str] = None
    strength: IdentityStrength = IdentityStrength.NONE
    is_cross_batch_stable: bool = False
    evidence: str = ""


class RecordKindPrediction(BaseModel):
    kind: OpportunityKind
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    needs_review: bool = False


class ParsedRow(BaseModel):
    row_number: int
    raw_values: dict[str, Any]
    canonical: CanonicalRecord
    row_hash: str
    identity: IdentityHint
    kind_prediction: RecordKindPrediction
    parse_status: ParseStatus = ParseStatus.PARSED
    errors: list[str] = Field(default_factory=list)


class ParsedSnapshot(BaseModel):
    path: Path
    file_name: str
    file_hash: str
    file_format: str
    source_name: str
    source_kind: SourceKind
    snapshot_at: Optional[datetime] = None
    header: list[str]
    mapping: dict[str, str]
    mapping_version: str
    rows: list[ParsedRow]
    rejected_rows: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def success_count(self) -> int:
        return sum(row.parse_status != ParseStatus.REJECTED for row in self.rows)
