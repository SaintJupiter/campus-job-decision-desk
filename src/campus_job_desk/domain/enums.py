from __future__ import annotations

from enum import Enum, IntEnum


class SourceKind(str, Enum):
    PAID_TABLE = "PAID_TABLE"
    PUBLIC_AGGREGATOR = "PUBLIC_AGGREGATOR"
    OFFICIAL = "OFFICIAL"
    SYNTHETIC = "SYNTHETIC"


class OpportunityKind(str, Enum):
    CAMPAIGN = "CAMPAIGN"
    POSTING = "POSTING"


class Authority(IntEnum):
    AGGREGATOR = 10
    OFFICIAL_CAMPAIGN = 20
    OFFICIAL_POSTING = 30
    USER_CONFIRMED = 40


class VerificationResult(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    NOT_FOUND = "NOT_FOUND"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class Eligibility(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class EvidenceFit(str, Enum):
    PRIMARY = "PRIMARY"
    APPLY = "APPLY"
    STRETCH = "STRETCH"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class Trust(str, Enum):
    VERIFIED = "VERIFIED"
    VERIFIED_WITH_CONFLICT = "VERIFIED_WITH_CONFLICT"
    CONSISTENT = "CONSISTENT"
    CONFLICTED = "CONFLICTED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ReviewDecision(str, Enum):
    UNDECIDED = "UNDECIDED"
    PREPARE_APPLY = "PREPARE_APPLY"
    VERIFY_FIRST = "VERIFY_FIRST"
    HOLD = "HOLD"
    REJECT = "REJECT"


class ApplicationStage(str, Enum):
    TO_APPLY = "TO_APPLY"
    APPLIED = "APPLIED"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DuplicateDecision(str, Enum):
    MERGE = "MERGE"
    SEPARATE = "SEPARATE"
    REVIEW = "REVIEW"


class ParseStatus(str, Enum):
    PARSED = "PARSED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class IdentityStrength(str, Enum):
    SOURCE_RECORD_ID = "SOURCE_RECORD_ID"
    OFFICIAL_JOB_ID = "OFFICIAL_JOB_ID"
    OFFICIAL_URL = "OFFICIAL_URL"
    COMPOUND_HINT = "COMPOUND_HINT"
    NONE = "NONE"


class FieldName(str, Enum):
    COMPANY = "company"
    TITLE = "title"
    CITIES = "cities"
    GRADUATION_YEARS = "graduation_years"
    EDUCATION = "education"
    RECRUITMENT_TYPE = "recruitment_type"
    EMPLOYER_TYPE = "employer_type"
    INDUSTRY = "industry"
    WRITTEN_TEST = "written_test"
    PUBLISHED_AT = "published_at"
    DEADLINE = "deadline"
    STATUS = "status"
    ANNOUNCEMENT_URL = "announcement_url"
    APPLY_URL = "apply_url"
    OFFICIAL_JOB_ID = "official_job_id"


class ResumeFormat(str, Enum):
    TEXT = "TEXT"
    MARKDOWN = "MARKDOWN"
    PDF = "PDF"


class ProfileFactKind(str, Enum):
    EDUCATION = "EDUCATION"
    GRADUATION_YEAR = "GRADUATION_YEAR"
    SKILL = "SKILL"
    EXPERIENCE = "EXPERIENCE"
    PROJECT = "PROJECT"
    LOCATION = "LOCATION"
