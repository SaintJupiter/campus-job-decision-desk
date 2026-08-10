from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update

from campus_job_desk.database import ENGINE, SessionLocal, create_schema
from campus_job_desk.domain.enums import ReviewDecision, VerificationResult
from campus_job_desk.models import (
    DecisionSnapshot,
    Opportunity,
    Organization,
    ProfileFact,
    ResumeDocument,
    ShortlistEntry,
    UserPreference,
    VerificationAttempt,
    WorkspaceMetadata,
)
from campus_job_desk.services.privacy import (
    PUBLIC_DEMO_MARKER_KEY,
    PUBLIC_DEMO_MARKER_VALUE,
    PUBLIC_DEMO_SEAL_KEY,
    compute_public_demo_content_seal,
    validate_public_demo_database,
)
from campus_job_desk.services.profile import ProfileService
from campus_job_desk.services.verification import record_verification
from campus_job_desk.services.workflow import compute_and_store_decision

DEMO_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "demo"
DEMO_RESUMES = (
    (DEMO_DATA_DIR / "小刘-机器人方向简历.md", False),
    (DEMO_DATA_DIR / "小刘-产品与解决方案简历.md", True),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the synthetic public demo")
    parser.add_argument(
        "--attest-fresh-reset",
        action="store_true",
        help="Attest that the exact demo database was reset before this seed run",
    )
    args = parser.parse_args()
    create_schema(ENGINE)
    with SessionLocal() as session:
        marker = session.get(WorkspaceMetadata, PUBLIC_DEMO_MARKER_KEY)
        if marker is None:
            if not args.attest_fresh_reset:
                raise RuntimeError(
                    "refusing to mark an existing workspace as synthetic; "
                    "run `make demo-db` to rebuild the exact public demo database"
                )
            _assert_fresh_seed_state(session)
            session.add(
                WorkspaceMetadata(
                    key=PUBLIC_DEMO_MARKER_KEY,
                    value=PUBLIC_DEMO_MARKER_VALUE,
                )
            )
        elif marker.value != PUBLIC_DEMO_MARKER_VALUE:
            raise RuntimeError("unexpected public demo data marker")
        else:
            from campus_job_desk.settings import get_settings

            validate_public_demo_database(session, get_settings().database_url)
            marker.value = PUBLIC_DEMO_MARKER_VALUE
        _seed_profile(session)
        for organization in session.scalars(select(Organization)):
            if organization.candidate_domain:
                organization.official_domain = organization.candidate_domain
                organization.official_domain_verified = True
                organization.official_domain_source = "synthetic-demo-fixture"
        opportunities = list(session.scalars(select(Opportunity)))
        by_job_id = {
            item.official_job_id: item
            for item in opportunities
            if item.official_job_id
        }
        verification_specs = {
            "PM1001": (
                VerificationResult.OPEN,
                "https://careers.star-sea.example/jobs/PM1001",
                "官网具体岗位页显示：负责大模型训练推理平台的需求梳理、能力设计与迭代；工作地为上海，2027届硕士可申请，申请按钮可用。",
                {
                    "cities": ["上海"],
                    "graduation_years": ["2027届"],
                    "education": ["硕士"],
                    "recruitment_type": "秋招",
                    "deadline": "2026-09-20",
                },
            ),
            "PM1002": (
                VerificationResult.BLOCKED,
                "https://careers.star-sea.example/jobs/PM1002",
                "页面触发访问限制，尚不能判断岗位是否关闭。",
                {},
            ),
            "DP2027": (
                VerificationResult.NOT_FOUND,
                "https://jobs.deepblue.example/position/DP2027",
                "原链接返回未找到，但没有官方关闭文案。",
                {},
            ),
        }
        verified_ids: list[str] = []
        for job_id, (result, url, evidence, fields) in verification_specs.items():
            opportunity = by_job_id.get(job_id)
            if opportunity is None:
                continue
            existing = session.scalar(
                select(VerificationAttempt).where(
                    VerificationAttempt.opportunity_id == opportunity.id,
                    VerificationAttempt.result == result.value,
                    VerificationAttempt.url == url,
                )
            )
            if existing is None:
                record_verification(
                    session,
                    opportunity_id=opportunity.id,
                    result=result,
                    url=url,
                    evidence_excerpt=evidence,
                    extracted_fields=fields,
                    reviewer="demo-fixture",
                )
            else:
                existing.evidence_scope = opportunity.kind
                existing.verified_domain = (
                    opportunity.organization.official_domain
                    if opportunity.organization
                    else ""
                )
            verified_ids.append(opportunity.id)
        session.flush()
        demo_ids = [item.id for item in opportunities]
        for opportunity_id in demo_ids:
            compute_and_store_decision(session, opportunity_id)
        primary = by_job_id.get("PM1001")
        if primary:
            latest = session.scalar(
                select(DecisionSnapshot)
                .where(DecisionSnapshot.opportunity_id == primary.id)
                .order_by(DecisionSnapshot.created_at.desc())
            )
            if latest and latest.manual_decision != ReviewDecision.PREPARE_APPLY.value:
                session.execute(
                    update(DecisionSnapshot)
                    .where(
                        DecisionSnapshot.opportunity_id == primary.id,
                        DecisionSnapshot.is_current.is_(True),
                    )
                    .values(is_current=False)
                )
                session.add(
                    DecisionSnapshot(
                        opportunity_id=latest.opportunity_id,
                        eligibility=latest.eligibility,
                        evidence_fit=latest.evidence_fit,
                        trust=latest.trust,
                        reasons=latest.reasons,
                        unknowns=latest.unknowns,
                        evidence_links=latest.evidence_links,
                        rule_version=latest.rule_version,
                        is_current=True,
                        manual_decision=ReviewDecision.PREPARE_APPLY.value,
                        override_reason="合成演示：加入今日投递清单",
                    )
                )
            shortlist_entry = session.get(ShortlistEntry, primary.id)
            if shortlist_entry is None:
                shortlist_entry = ShortlistEntry(
                    opportunity_id=primary.id,
                    priority=100,
                    note="合成演示：官网已核验，优先投递",
                )
                session.add(shortlist_entry)
            shortlist_entry.application_stage = "TO_APPLY"
            shortlist_entry.next_action = "完成网申，并记录所用简历版本"
            shortlist_entry.next_action_at = datetime.now(timezone.utc) + timedelta(days=1)
        session.commit()
        content_seal = compute_public_demo_content_seal(session)
        seal = session.get(WorkspaceMetadata, PUBLIC_DEMO_SEAL_KEY)
        if seal is None:
            session.add(
                WorkspaceMetadata(key=PUBLIC_DEMO_SEAL_KEY, value=content_seal)
            )
        else:
            seal.value = content_seal
        session.commit()
        print(
            json.dumps(
                {
                    "profile_facts": session.query(ProfileFact).count(),
                    "opportunities": len(demo_ids),
                    "verified": len(verified_ids),
                    "seeded_at": datetime.now(timezone.utc).isoformat(),
                    "data_notice": "synthetic demo data only",
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def _assert_fresh_seed_state(session) -> None:  # type: ignore[no-untyped-def]
    """Fail closed before issuing the one-time fully-synthetic attestation."""

    from campus_job_desk.domain.enums import SourceKind
    from campus_job_desk.models import DataSource

    non_synthetic = list(
        session.scalars(select(DataSource).where(DataSource.kind != SourceKind.SYNTHETIC.value))
    )
    if non_synthetic:
        raise RuntimeError("demo seed contains a non-synthetic data source")
    protected_counts = {
        "profile facts": session.query(ProfileFact).count(),
        "preferences": session.query(UserPreference).count(),
        "decisions": session.query(DecisionSnapshot).count(),
        "shortlist entries": session.query(ShortlistEntry).count(),
    }
    contaminated = {name: count for name, count in protected_counts.items() if count}
    if contaminated:
        raise RuntimeError(
            "demo seed is not fresh; refusing to attest potentially personal data: "
            + json.dumps(contaminated, ensure_ascii=False, sort_keys=True)
        )


def _seed_profile(session) -> None:  # type: ignore[no-untyped-def]
    if session.scalar(select(ProfileFact.id).limit(1)) is None:
        for resume_path, is_active in DEMO_RESUMES:
            content = resume_path.read_bytes()
            profile = ProfileService().extract_file(resume_path)
            resume_document = ResumeDocument(
                name=resume_path.name,
                source_format=profile.source_format.value,
                content_hash=hashlib.sha256(content).hexdigest(),
                is_active=is_active,
            )
            session.add(resume_document)
            session.flush()
            for candidate in profile.facts:
                session.add(
                    ProfileFact(
                        resume_document_id=resume_document.id,
                        category=candidate.kind.value,
                        label=candidate.value,
                        value=candidate.value,
                        evidence_text=candidate.evidence_text,
                        evidence_start=candidate.span.start,
                        evidence_end=candidate.span.end,
                        provenance=candidate.provenance.model_dump_json(),
                        confirmed=True,
                    )
                )
    preferences = {
        "accepted_cities": (["上海"], True),
        "accepted_recruitment_types": (["校招"], True),
        "target_role_keywords": (["AI产品", "数据产品", "技术产品"], False),
        "excluded_work_patterns": (["强销售指标", "长期驻场"], False),
    }
    for key, (value, hard_constraint) in preferences.items():
        item = session.get(UserPreference, key)
        encoded = json.dumps(value, ensure_ascii=False)
        if item is None:
            session.add(
                UserPreference(
                    key=key,
                    value=encoded,
                    hard_constraint=hard_constraint,
                    confirmed=True,
                )
            )
        else:
            item.value = encoded
            item.hard_constraint = hard_constraint
            item.confirmed = True
    session.flush()


if __name__ == "__main__":
    main()
