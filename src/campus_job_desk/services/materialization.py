from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from campus_job_desk.domain.enums import (
    Authority,
    IdentityStrength,
    OpportunityKind,
    ParseStatus,
    SourceKind,
)
from campus_job_desk.domain.normalize import (
    clean_text,
    normalize_company,
    normalize_url,
    stable_json,
)
from campus_job_desk.domain.schemas import CanonicalRecord
from campus_job_desk.models import FieldClaim, ImportBatch, Opportunity, RawRecord
from campus_job_desk.repositories.opportunities import (
    add_field_claim,
    create_opportunity,
    find_by_source_record,
    find_origin_opportunity,
    get_or_create_organization,
    link_origin,
    opportunities_by_canonical_key,
    opportunities_by_official_job_id,
    refresh_claim_selections,
)

from .dedup import create_duplicate_candidates

COPYRIGHT_MARKERS = ("正版授权", "转售必究")


@dataclass(frozen=True)
class MaterializationResult:
    batch_id: str
    raw_count: int
    created_opportunities: int
    reused_opportunities: int
    skipped_records: int
    created_claims: int
    created_duplicate_candidates: int


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _candidate_domain(record: CanonicalRecord) -> str:
    url = normalize_url(record.apply_url or record.announcement_url)
    return (urlparse(url).hostname or "").lower().rstrip(".") if url else ""


def _trusted_import_domain(record: CanonicalRecord, source_kind: str) -> str:
    del record, source_kind
    # A client-controlled source label is never an authenticated trust root.
    # Controlled demo fixtures promote candidate domains in the seed script.
    return ""


def _official_url(record: CanonicalRecord) -> str:
    return normalize_url(record.apply_url or record.announcement_url)


def _canonical_key(
    record: CanonicalRecord,
    *,
    normalized_organization: str,
    source_id: str,
    allow_url_exact_match: bool,
    allow_job_identity: bool,
) -> str | None:
    if record.official_job_id and allow_job_identity:
        return f"official-job:{normalized_organization}:{record.official_job_id.lower()}"
    official_url = _official_url(record)
    if official_url and allow_url_exact_match:
        return f"official-url:{official_url}"
    if record.source_record_id:
        return f"source-record:{source_id}:{record.source_record_id}"
    return None


def _title_key(value: str) -> str:
    return clean_text(value).replace(" ", "").lower()


def _has_explicit_official_job_id(
    batch: ImportBatch,
    raw_record: RawRecord,
) -> bool:
    try:
        mapping = json.loads(batch.mapping_json)
        raw_payload = json.loads(raw_record.raw_payload)
    except (TypeError, json.JSONDecodeError):
        return False
    source_column = mapping.get("official_job_id")
    return bool(source_column and clean_text(raw_payload.get(source_column)))


def _authority(
    source_kind: str,
    opportunity_kind: str,
    *,
    official_domain_verified: bool,
) -> int:
    if source_kind == SourceKind.OFFICIAL.value and official_domain_verified:
        if opportunity_kind == OpportunityKind.POSTING.value:
            return int(Authority.OFFICIAL_POSTING)
        return int(Authority.OFFICIAL_CAMPAIGN)
    return int(Authority.AGGREGATOR)


def _normalized_claim_value(field_name: str, value: object) -> object:
    if field_name == "company":
        return normalize_company(value)
    if field_name == "title":
        return clean_text(value).replace(" ", "").lower()
    if field_name in {"cities", "graduation_years", "education"}:
        return sorted({clean_text(item) for item in list(value) if clean_text(item)})
    if field_name in {"announcement_url", "apply_url"}:
        return normalize_url(value)
    return clean_text(value)


def _claim_values(record: CanonicalRecord) -> dict[str, object]:
    return {
        "company": record.company,
        "title": record.title,
        "cities": record.cities,
        "graduation_years": record.graduation_years,
        "education": record.education,
        "recruitment_type": record.recruitment_type,
        "industry": record.industry,
        "employer_type": record.employer_type,
        "written_test": record.written_test,
        "published_at": record.published_at,
        "deadline": record.deadline,
        # Aggregated rows do not establish official openness. The explicit UNKNOWN
        # observation prevents a missing field from becoming an inferred OPEN state.
        "status": "UNKNOWN",
        "announcement_url": record.announcement_url,
        "apply_url": record.apply_url,
    }


def _find_exact_opportunity(
    session: Session,
    *,
    record: CanonicalRecord,
    organization_id: str,
    canonical_key: str | None,
    source_id: str,
    predicted_kind: str,
    official_job_id_is_explicit: bool,
) -> Opportunity | None:
    if record.official_job_id and predicted_kind == OpportunityKind.POSTING.value:
        candidates = opportunities_by_official_job_id(
            session,
            organization_id=organization_id,
            official_job_id=record.official_job_id,
        )
        for candidate in candidates:
            if candidate.kind != predicted_kind:
                continue
            if official_job_id_is_explicit or _title_key(candidate.display_title) == _title_key(
                record.title
            ):
                return candidate
    if canonical_key and canonical_key.startswith("official-url:"):
        candidates = opportunities_by_canonical_key(
            session,
            canonical_key=canonical_key,
            organization_id=organization_id,
        )
        for candidate in candidates:
            if (
                candidate.kind == predicted_kind
                and _title_key(candidate.display_title) == _title_key(record.title)
            ):
                return candidate
    candidate: Opportunity | None = None
    if record.source_record_id:
        candidate = find_by_source_record(
            session,
            source_id=source_id,
            source_record_id=record.source_record_id,
        )
    if candidate is None:
        return None
    if candidate.organization_id != organization_id:
        # Supplier row ids are only stable within the same company identity. Reuse
        # across companies would silently mix provenance and verification anchors.
        return None
    if candidate.kind != predicted_kind:
        return None
    if (
        candidate.official_job_id
        and record.official_job_id
        and candidate.official_job_id != record.official_job_id
    ):
        return None
    if record.official_job_id and not candidate.official_job_id:
        candidate.official_job_id = record.official_job_id
        candidate.canonical_key = canonical_key
    return candidate


def _materialize_claims(
    session: Session,
    *,
    opportunity: Opportunity,
    raw_record: RawRecord,
    record: CanonicalRecord,
    batch: ImportBatch,
) -> int:
    observed_at = _aware(batch.snapshot_at or batch.imported_at or raw_record.created_at)
    source = batch.source
    evidence_url = _official_url(record)
    evidence_label = f"{source.name} · {batch.file_name} · row {raw_record.row_number}"
    authority = _authority(
        source.kind,
        opportunity.kind,
        official_domain_verified=bool(
            opportunity.organization
            and opportunity.organization.official_domain_verified
        ),
    )
    created = 0
    field_names: list[str] = []
    for field_name, value in _claim_values(record).items():
        normalized = _normalized_claim_value(field_name, value)
        _, was_created = add_field_claim(
            session,
            opportunity_id=opportunity.id,
            raw_record_id=raw_record.id,
            field_name=field_name,
            raw_value=stable_json(value),
            normalized_value=stable_json(normalized),
            authority=authority,
            observed_at=observed_at,
            evidence_label=evidence_label,
            evidence_url=evidence_url,
            parser=f"source-import/{batch.file_format}",
            parser_version=batch.mapping_version,
            confidence=0.0 if field_name == "status" else 1.0,
            check_existing=False,
            flush=False,
        )
        created += int(was_created)
        field_names.append(field_name)
    if record.official_job_id:
        _, was_created = add_field_claim(
            session,
            opportunity_id=opportunity.id,
            raw_record_id=raw_record.id,
            field_name="official_job_id",
            raw_value=stable_json(record.official_job_id),
            normalized_value=stable_json(record.official_job_id.lower()),
            authority=authority,
            observed_at=observed_at,
            evidence_label=evidence_label,
            evidence_url=evidence_url,
            parser=f"source-import/{batch.file_format}",
            parser_version=batch.mapping_version,
            confidence=1.0,
            check_existing=False,
            flush=False,
        )
        created += int(was_created)
        field_names.append("official_job_id")
    session.flush()
    refresh_claim_selections(session, opportunity.id, field_names)
    selected_title = session.scalar(
        select(FieldClaim).where(
            FieldClaim.opportunity_id == opportunity.id,
            FieldClaim.field_name == "title",
            FieldClaim.active.is_(True),
            FieldClaim.selected.is_(True),
        )
    )
    if selected_title is not None:
        try:
            display_title = json.loads(selected_title.raw_value)
        except (TypeError, json.JSONDecodeError):
            display_title = selected_title.raw_value
        if isinstance(display_title, str) and clean_text(display_title):
            opportunity.display_title = clean_text(display_title)
    return created


def materialize_batch(session: Session, batch_id: str) -> MaterializationResult:
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        raise ValueError(f"导入批次不存在：{batch_id}")

    raw_records = list(
        session.scalars(
            select(RawRecord)
            .where(RawRecord.batch_id == batch_id)
            .order_by(RawRecord.row_number)
        )
    )
    created_opportunities = 0
    reused_opportunities = 0
    skipped_records = 0
    created_claims = 0
    created_candidates = 0
    try:
        for raw_record in raw_records:
            if find_origin_opportunity(session, raw_record.id) is not None:
                skipped_records += 1
                continue
            if raw_record.parse_status == ParseStatus.REJECTED.value:
                skipped_records += 1
                continue
            record = CanonicalRecord.model_validate_json(raw_record.canonical_payload)
            if (
                not record.company
                or not record.title
                or any(marker in record.company for marker in COPYRIGHT_MARKERS)
            ):
                skipped_records += 1
                continue

            normalized_organization = normalize_company(record.company)
            trusted_import_domain = _trusted_import_domain(
                record, batch.source.kind
            )
            organization, _ = get_or_create_organization(
                session,
                canonical_name=record.company,
                normalized_name=normalized_organization,
                candidate_domain=_candidate_domain(record),
                official_domain=trusted_import_domain,
                official_domain_verified=bool(trusted_import_domain),
                official_domain_source=(
                    f"source:{batch.source_id}" if trusted_import_domain else ""
                ),
            )
            canonical_key = _canonical_key(
                record,
                normalized_organization=normalized_organization,
                source_id=batch.source_id,
                allow_url_exact_match=(
                    raw_record.kind_prediction == OpportunityKind.POSTING.value
                    and not raw_record.needs_review
                ),
                allow_job_identity=(
                    raw_record.kind_prediction == OpportunityKind.POSTING.value
                ),
            )
            opportunity = _find_exact_opportunity(
                session,
                record=record,
                organization_id=organization.id,
                canonical_key=canonical_key,
                source_id=batch.source_id,
                predicted_kind=raw_record.kind_prediction,
                official_job_id_is_explicit=_has_explicit_official_job_id(
                    batch,
                    raw_record,
                ),
            )
            opportunity_was_created = opportunity is None
            if opportunity_was_created:
                review_status = (
                    "REVIEW"
                    if raw_record.identity_strength
                    in {IdentityStrength.COMPOUND_HINT.value, IdentityStrength.NONE.value}
                    or raw_record.needs_review
                    else "PENDING"
                )
                opportunity = create_opportunity(
                    session,
                    organization_id=organization.id,
                    kind=raw_record.kind_prediction,
                    display_title=record.title,
                    canonical_key=canonical_key,
                    official_job_id=(
                        record.official_job_id
                        if raw_record.kind_prediction == OpportunityKind.POSTING.value
                        else None
                    ),
                    review_status=review_status,
                )
                created_opportunities += 1
            else:
                reused_opportunities += 1

            assert opportunity is not None
            link_origin(
                session,
                opportunity_id=opportunity.id,
                raw_record_id=raw_record.id,
            )
            created_claims += _materialize_claims(
                session,
                opportunity=opportunity,
                raw_record=raw_record,
                record=record,
                batch=batch,
            )
            if not opportunity_was_created:
                from .workflow import invalidate_decisions

                invalidate_decisions(session, opportunity_ids=[opportunity.id])
            if opportunity_was_created and raw_record.identity_strength in {
                IdentityStrength.COMPOUND_HINT.value,
                IdentityStrength.NONE.value,
            }:
                created_candidates += create_duplicate_candidates(
                    session,
                    opportunity=opportunity,
                    raw_record=raw_record,
                    canonical=record,
                )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return MaterializationResult(
        batch_id=batch_id,
        raw_count=len(raw_records),
        created_opportunities=created_opportunities,
        reused_opportunities=reused_opportunities,
        skipped_records=skipped_records,
        created_claims=created_claims,
        created_duplicate_candidates=created_candidates,
    )
