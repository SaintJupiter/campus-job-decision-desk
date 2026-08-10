from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from campus_job_desk.api.app import app
from campus_job_desk.database import get_session
from campus_job_desk.domain.enums import (
    Authority,
    Eligibility,
    EvidenceFit,
    OpportunityKind,
    Trust,
    VerificationResult,
)
from campus_job_desk.models import (
    DecisionSnapshot,
    DuplicateCandidate,
    FieldClaim,
    Opportunity,
    Organization,
    ProfileFact,
    ShortlistEntry,
    UserPreference,
    VerificationAttempt,
)
from campus_job_desk.services.workflow import (
    build_decision_context,
    decision_rule_version,
    load_evidence_profile,
)


def _client(session: Session) -> TestClient:
    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def _opportunity(session: Session, *, kind: OpportunityKind) -> Opportunity:
    organization = Organization(
        canonical_name="星河科技",
        normalized_name="星河科技",
        official_domain="careers.example.com",
        official_domain_verified=True,
        official_domain_source="test-fixture",
    )
    session.add(organization)
    session.flush()
    item = Opportunity(
        organization_id=organization.id,
        kind=kind.value,
        display_title="AI 产品经理" if kind == OpportunityKind.POSTING else "2027 校园招聘",
        official_job_id="A-1001" if kind == OpportunityKind.POSTING else None,
        review_status="READY",
    )
    session.add(item)
    session.flush()
    return item


def _claim(session: Session, opportunity_id: str, field: str, value: object) -> None:
    session.add(
        FieldClaim(
            opportunity_id=opportunity_id,
            field_name=field,
            raw_value=str(value),
            normalized_value=json.dumps(value, ensure_ascii=False),
            authority=int(Authority.AGGREGATOR),
            observed_at=datetime.now(timezone.utc),
            evidence_label="测试来源",
            parser="fixture",
            parser_version="v1",
            confidence=1,
            selected=True,
        )
    )


def _decision(session: Session, opportunity_id: str) -> None:
    opportunity = session.get(Opportunity, opportunity_id)
    assert opportunity is not None
    session.add(
        DecisionSnapshot(
            opportunity_id=opportunity_id,
            eligibility=Eligibility.PASS.value,
            evidence_fit=EvidenceFit.APPLY.value,
            trust=Trust.VERIFIED.value,
            reasons=json.dumps(["硬条件明确满足"], ensure_ascii=False),
            unknowns="[]",
            evidence_links="[]",
            rule_version=decision_rule_version(
                load_evidence_profile(session),
                build_decision_context(session, opportunity),
            ),
        )
    )


def test_campaign_cannot_enter_shortlist(db_session: Session) -> None:
    campaign = _opportunity(db_session, kind=OpportunityKind.CAMPAIGN)
    _decision(db_session, campaign.id)
    db_session.add(
        VerificationAttempt(
            opportunity_id=campaign.id,
            result=VerificationResult.OPEN.value,
            evidence_scope=OpportunityKind.CAMPAIGN.value,
            verified_domain="careers.example.com",
            url="https://careers.example.com/campus",
            checked_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    with _client(db_session) as client:
        response = client.post(f"/api/workspace/shortlist/{campaign.id}", json={})

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert "招聘项目线索" in response.json()["detail"]
    assert db_session.get(ShortlistEntry, campaign.id) is None


def test_domestic_campus_filters_cover_batch_employer_test_and_deadline(
    db_session: Session,
) -> None:
    urgent = _opportunity(db_session, kind=OpportunityKind.POSTING)
    urgent.display_title = "工业软件产品经理"
    urgent.official_job_id = "URGENT-1"
    later = Opportunity(
        organization_id=urgent.organization_id,
        kind=OpportunityKind.POSTING.value,
        display_title="数据产品经理",
        official_job_id="LATER-1",
        review_status="READY",
    )
    db_session.add(later)
    db_session.flush()
    for field, value in (
        ("recruitment_type", "提前批"),
        ("employer_type", "国企"),
        ("written_test", "免笔试"),
        ("deadline", (datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat()),
    ):
        _claim(db_session, urgent.id, field, value)
    for field, value in (
        ("recruitment_type", "秋招"),
        ("employer_type", "民营企业"),
        ("written_test", "有笔试"),
        ("deadline", (datetime.now(timezone.utc) + timedelta(days=45)).date().isoformat()),
    ):
        _claim(db_session, later.id, field, value)
    db_session.commit()

    with _client(db_session) as client:
        response = client.get(
            "/api/opportunities",
            params={
                "recruitment_type": "提前批",
                "employer_type": "国企",
                "written_test": "免笔试",
                "deadline_within_days": 7,
                "sort": "deadline",
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["title"] == "工业软件产品经理"
    assert payload["items"][0]["employer_type"] == "国企"
    assert payload["items"][0]["written_test"] == "免笔试"


def test_application_progress_tracks_stage_and_next_action(
    db_session: Session,
) -> None:
    posting = _opportunity(db_session, kind=OpportunityKind.POSTING)
    db_session.add(
        ShortlistEntry(
            opportunity_id=posting.id,
            priority=90,
            note="优先投递",
        )
    )
    db_session.commit()

    next_action_at = datetime.now(timezone.utc) + timedelta(days=2)
    with _client(db_session) as client:
        updated = client.patch(
            f"/api/workspace/shortlist/{posting.id}/application",
            json={
                "stage": "APPLIED",
                "next_action": "准备笔试题型并复盘投递材料",
                "next_action_at": next_action_at.isoformat(),
            },
        )
        listed = client.get("/api/workspace/shortlist")

    app.dependency_overrides.clear()
    assert updated.status_code == 200
    assert updated.json()["application_stage"] == "APPLIED"
    row = listed.json()[0]
    assert row["application_stage"] == "APPLIED"
    assert row["next_action"] == "准备笔试题型并复盘投递材料"
    assert row["applied_at"] is not None


def test_not_found_verification_stays_distinct_and_claims_only_explicit_fields(
    db_session: Session,
) -> None:
    posting = _opportunity(db_session, kind=OpportunityKind.POSTING)
    _claim(db_session, posting.id, "graduation_years", ["2027"])
    db_session.commit()

    with _client(db_session) as client:
        response = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "NOT_FOUND",
                "url": "https://careers.example.com/jobs/A-1001",
                "evidence_excerpt": "页面返回 404，未出现明确关闭文案",
                "extracted_fields": {},
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["result"] == "NOT_FOUND"
    verification = db_session.scalar(
        select(VerificationAttempt).where(VerificationAttempt.opportunity_id == posting.id)
    )
    assert verification is not None
    assert verification.result == VerificationResult.NOT_FOUND.value
    official_fields = set(
        db_session.scalars(
            select(FieldClaim.field_name).where(FieldClaim.verification_id == verification.id)
        )
    )
    assert official_fields == set()
    graduation_claim = db_session.scalar(
        select(FieldClaim).where(
            FieldClaim.opportunity_id == posting.id,
            FieldClaim.field_name == "graduation_years",
        )
    )
    assert graduation_claim is not None
    assert graduation_claim.normalized_value == '["2027"]'


def test_verified_posting_can_be_shortlisted_and_exported(db_session: Session) -> None:
    posting = _opportunity(db_session, kind=OpportunityKind.POSTING)
    for field, value in (
        ("company", "星河科技"),
        ("cities", ["上海"]),
        ("apply_url", "https://careers.example.com/jobs/A-1001"),
    ):
        _claim(db_session, posting.id, field, value)
    db_session.add(
        VerificationAttempt(
            opportunity_id=posting.id,
            result=VerificationResult.OPEN.value,
            evidence_scope=OpportunityKind.POSTING.value,
            verified_domain="careers.example.com",
            url="https://careers.example.com/jobs/A-1001",
            checked_at=datetime.now(timezone.utc),
            evidence_excerpt="页面显示申请按钮",
        )
    )
    db_session.flush()
    _decision(db_session, posting.id)
    db_session.commit()

    with _client(db_session) as client:
        formula_note = '=HYPERLINK("https://example.test","x")'
        added = client.post(
            f"/api/workspace/shortlist/{posting.id}",
            json={"priority": 90, "note": formula_note},
        )
        exported = client.get("/api/workspace/shortlist/export?format=json")
        exported_csv = client.get("/api/workspace/shortlist/export?format=csv")

    app.dependency_overrides.clear()
    assert added.status_code == 201
    assert exported.status_code == 200
    rows = exported.json()
    assert rows[0]["company"] == "星河科技"
    assert rows[0]["title"] == "AI 产品经理"
    assert rows[0]["eligibility"] == "PASS"
    assert rows[0]["verification"] == "OPEN"
    assert rows[0]["note"] == formula_note
    csv_rows = list(csv.DictReader(io.StringIO(exported_csv.text.lstrip("\ufeff"))))
    assert csv_rows[0]["note"] == "'" + formula_note
    current_count = db_session.scalar(
        select(func.count(DecisionSnapshot.id)).where(
            DecisionSnapshot.opportunity_id == posting.id,
            DecisionSnapshot.is_current.is_(True),
        )
    )
    assert current_count == 1


def test_profile_evidence_drives_persisted_three_axis_decision(db_session: Session) -> None:
    posting = _opportunity(db_session, kind=OpportunityKind.POSTING)
    for field, value in (
        ("cities", ["上海"]),
        ("graduation_years", ["2027"]),
        ("education", ["本科及以上"]),
        ("recruitment_type", "秋招"),
        ("apply_url", "https://careers.example.com/jobs/A-1001"),
    ):
        _claim(db_session, posting.id, field, value)
    resume_line = "2027届硕士，使用 Python 完成 AI 产品需求与数据分析。"
    for category, value in (
        ("GRADUATION_YEAR", "2027届"),
        ("EDUCATION", "硕士"),
        ("SKILL", "AI"),
        ("SKILL", "产品"),
    ):
        db_session.add(
            ProfileFact(
                category=category,
                label=value,
                value=value,
                evidence_text=resume_line,
                evidence_start=0,
                evidence_end=len(resume_line),
                provenance=json.dumps(
                    {
                        "source_type": "resume",
                        "source_name": "fixture.txt",
                        "extraction_method": "fixture",
                    },
                    ensure_ascii=False,
                ),
                confirmed=True,
            )
        )
    db_session.add_all(
        [
            UserPreference(
                key="accepted_cities",
                value='["上海"]',
                hard_constraint=True,
                confirmed=True,
            ),
            UserPreference(
                key="accepted_recruitment_types",
                value='["校招"]',
                hard_constraint=True,
                confirmed=True,
            ),
        ]
    )
    db_session.add(
        VerificationAttempt(
            opportunity_id=posting.id,
            result=VerificationResult.OPEN.value,
            evidence_scope=OpportunityKind.POSTING.value,
            verified_domain="careers.example.com",
            url="https://careers.example.com/jobs/A-1001",
            checked_at=datetime.now(timezone.utc),
            evidence_excerpt="具体岗位页面显示申请按钮",
        )
    )
    db_session.commit()

    with _client(db_session) as client:
        recomputed = client.post(
            "/api/workspace/decisions/recompute",
            json={"opportunity_ids": [posting.id]},
        )
        detail = client.get(f"/api/opportunities/{posting.id}")

    app.dependency_overrides.clear()
    assert recomputed.status_code == 200
    assert recomputed.json() == {"recomputed": 1}
    assert detail.status_code == 200
    decision = detail.json()["decision_history"][0]
    assert decision["eligibility"] == "PASS"
    assert decision["evidence_fit"] in {"PRIMARY", "APPLY"}
    assert decision["trust"] == "VERIFIED"
    assert decision["evidence_links"]


def test_source_preview_and_import_materialize_without_losing_raw_rows(
    db_session: Session,
) -> None:
    fixture = Path("data/demo/source_alpha.csv")
    content = fixture.read_bytes()
    with _client(db_session) as client:
        preview = client.post(
            "/api/sources/preview",
            files={"file": (fixture.name, content, "text/csv")},
            data={"source_name": "演示来源 A", "source_kind": "PAID_TABLE"},
        )
        imported = client.post(
            "/api/sources/import",
            files={"file": (fixture.name, content, "text/csv")},
            data={
                "source_id": "demo-alpha-api",
                "source_name": "演示来源 A",
                "source_kind": "PAID_TABLE",
                "independence_group": "demo-alpha-api",
            },
        )
        opportunities = client.get("/api/opportunities?page_size=100")

    app.dependency_overrides.clear()
    assert preview.status_code == 200
    assert preview.json()["row_count"] == 5
    assert sum(preview.json()["kind_counts"].values()) == 5
    assert imported.status_code == 201
    assert imported.json()["row_count"] == 5
    assert imported.json()["materialized_count"] == 5
    assert opportunities.status_code == 200
    assert opportunities.json()["total"] == 5


def test_source_preview_marks_copyright_row_as_non_job(db_session: Session) -> None:
    content = (
        "公司名称\t招聘岗位\t截止日期\n"
        "━━━━ 【柴柴学长list】 正版授权 · 转售必究 ━━━━\t"
        "本表受著作权法保护 · 转售将追究法律责任\t请通过官方店铺购买\n"
    ).encode()
    with _client(db_session) as client:
        response = client.post(
            "/api/sources/preview",
            files={"file": ("public-share.tsv", content, "text/tab-separated-values")},
            data={"source_name": "公开分享页", "source_kind": "PUBLIC_AGGREGATOR"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind_counts"] == {"CAMPAIGN": 0, "POSTING": 0, "NON_JOB": 1}
    assert payload["sample_rows"][0]["kind"]["kind"] == "NON_JOB"
    assert payload["sample_rows"][0]["kind"]["needs_review"] is False


def test_upload_api_cannot_create_a_trusted_synthetic_source(db_session: Session) -> None:
    fixture = Path("data/demo/source_alpha.csv")
    with _client(db_session) as client:
        response = client.post(
            "/api/sources/import",
            files={"file": (fixture.name, fixture.read_bytes(), "text/csv")},
            data={
                "source_id": "untrusted-synthetic",
                "source_name": "用户自称合成源",
                "source_kind": "SYNTHETIC",
                "independence_group": "untrusted-synthetic",
            },
        )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert "受控演示种子" in response.json()["detail"]
    assert db_session.scalar(select(Organization)) is None


def test_import_rejects_existing_source_identity_rewrite(db_session: Session) -> None:
    fixture = Path("data/demo/source_alpha.csv")
    common = {
        "source_id": "same-source",
        "source_name": "供应商甲",
        "source_kind": "PAID_TABLE",
        "independence_group": "vendor-a",
    }
    with _client(db_session) as client:
        first = client.post(
            "/api/sources/import",
            files={"file": (fixture.name, fixture.read_bytes(), "text/csv")},
            data=common,
        )
        rewritten = client.post(
            "/api/sources/import",
            files={"file": (fixture.name, fixture.read_bytes(), "text/csv")},
            data={**common, "source_name": "供应商乙", "independence_group": "vendor-b"},
        )

    app.dependency_overrides.clear()
    assert first.status_code == 201
    assert rewritten.status_code == 409
    assert "来源名称" in rewritten.json()["detail"]


def test_runtime_meta_and_server_side_decision_queue_are_not_first_page_limited(
    db_session: Session,
) -> None:
    organization = Organization(
        canonical_name="队列测试公司",
        normalized_name="队列测试公司",
        official_domain="",
        official_domain_verified=False,
    )
    db_session.add(organization)
    db_session.flush()
    db_session.add_all(
        [
            Opportunity(
                organization_id=organization.id,
                kind=OpportunityKind.CAMPAIGN.value,
                display_title=f"招聘项目 {index:03d}",
                review_status="REVIEW",
            )
            for index in range(105)
        ]
    )
    db_session.commit()

    with _client(db_session) as client:
        meta = client.get("/api/meta")
        dashboard = client.get("/api/workspace/dashboard")
        first = client.get("/api/workspace/decision-queue?queue=verify_first&page=1&page_size=100")
        second = client.get("/api/workspace/decision-queue?queue=verify_first&page=2&page_size=100")

    app.dependency_overrides.clear()
    assert meta.status_code == 200
    assert meta.json()["data_mode"] == "local-workspace"
    assert meta.json()["read_only"] is False
    assert dashboard.json()["verify_first_count"] == 105
    assert first.status_code == 200
    assert first.json()["total"] == 105
    assert len(first.json()["items"]) == 100
    assert len(second.json()["items"]) == 5


def test_dashboard_distinguishes_tracked_shortlist_from_ready_shortlist(
    db_session: Session,
) -> None:
    posting = _opportunity(db_session, kind=OpportunityKind.POSTING)
    for field, value in (
        ("cities", ["上海"]),
        ("graduation_years", ["2027"]),
        ("apply_url", "https://careers.example.com/jobs/A-1001"),
    ):
        _claim(db_session, posting.id, field, value)
    db_session.add(
        VerificationAttempt(
            opportunity_id=posting.id,
            result=VerificationResult.OPEN.value,
            evidence_scope=OpportunityKind.POSTING.value,
            verified_domain="careers.example.com",
            url="https://careers.example.com/jobs/A-1001",
            checked_at=datetime.now(timezone.utc),
            evidence_excerpt="页面显示申请按钮",
        )
    )
    db_session.flush()
    _decision(db_session, posting.id)
    campaign_org = Organization(
        canonical_name="项目线索公司",
        normalized_name="项目线索公司",
        official_domain="",
        official_domain_verified=False,
    )
    db_session.add(campaign_org)
    db_session.flush()
    campaign = Opportunity(
        organization_id=campaign_org.id,
        kind=OpportunityKind.CAMPAIGN.value,
        display_title="2027 秋招项目",
        review_status="REVIEW",
    )
    db_session.add(campaign)
    db_session.flush()
    db_session.add_all(
        [
            ShortlistEntry(opportunity_id=posting.id, priority=90),
            ShortlistEntry(opportunity_id=campaign.id, priority=10),
        ]
    )
    db_session.commit()

    with _client(db_session) as client:
        dashboard = client.get("/api/workspace/dashboard")
        ready_queue = client.get("/api/workspace/decision-queue?queue=ready")

    app.dependency_overrides.clear()
    assert dashboard.status_code == 200
    assert dashboard.json()["shortlist_total_count"] == 2
    assert dashboard.json()["shortlist_ready_count"] == 1
    assert dashboard.json()["ready_count"] == 1
    assert dashboard.json()["verify_first_count"] == 1
    assert ready_queue.json()["total"] == 1


def test_stale_verified_decision_disappears_from_ready_queue(db_session: Session) -> None:
    posting = _opportunity(db_session, kind=OpportunityKind.POSTING)
    db_session.add(
        VerificationAttempt(
            opportunity_id=posting.id,
            result=VerificationResult.OPEN.value,
            evidence_scope=OpportunityKind.POSTING.value,
            verified_domain="careers.example.com",
            url="https://careers.example.com/jobs/A-1001",
            checked_at=datetime.now(timezone.utc) - timedelta(days=14, seconds=1),
            evidence_excerpt="曾显示申请按钮",
        )
    )
    db_session.flush()
    _decision(db_session, posting.id)
    db_session.commit()

    with _client(db_session) as client:
        ready_queue = client.get("/api/workspace/decision-queue?queue=ready")
        verify_queue = client.get("/api/workspace/decision-queue?queue=verify_first")

    app.dependency_overrides.clear()
    assert ready_queue.json()["total"] == 0
    assert verify_queue.json()["total"] == 1


def test_resume_upload_is_evidence_bound_and_can_be_deleted(db_session: Session) -> None:
    resume = "教育背景：2027届硕士\n项目：使用 Python 完成 AI 产品需求分析与数据评测。"
    with _client(db_session) as client:
        uploaded = client.post(
            "/api/workspace/profile/upload",
            files={"file": ("resume.txt", resume.encode("utf-8"), "text/plain")},
        )
        profile = client.get("/api/workspace/profile")
        deleted = client.delete("/api/workspace/profile")
        empty_profile = client.get("/api/workspace/profile")

    app.dependency_overrides.clear()
    assert uploaded.status_code == 201
    assert uploaded.json()["created"] >= 4
    assert profile.status_code == 200
    assert all(item["evidence_text"] in resume for item in profile.json()["facts"])
    assert all(item["confirmed"] is False for item in profile.json()["facts"])
    assert deleted.status_code == 204
    assert empty_profile.json()["facts"] == []
    assert empty_profile.json()["resumes"] == []


def test_resume_versions_are_retained_but_only_active_version_drives_profile(
    db_session: Session,
) -> None:
    first_text = "2027届硕士，负责 AI 产品需求分析。"
    second_text = "2027届硕士，使用 SQL 完成数据分析。"
    with _client(db_session) as client:
        first = client.post(
            "/api/workspace/profile/extract",
            json={"text": first_text, "source_name": "AI产品简历.txt"},
        )
        second = client.post(
            "/api/workspace/profile/extract",
            json={"text": second_text, "source_name": "数据分析简历.txt"},
        )
        profile = client.get("/api/workspace/profile").json()
        activated = client.put(
            f"/api/workspace/profile/resumes/{first.json()['resume_document_id']}/activate"
        )

    app.dependency_overrides.clear()
    assert first.status_code == 201
    assert second.status_code == 201
    assert len(profile["resumes"]) == 2
    assert profile["active_resume_id"] == second.json()["resume_document_id"]
    assert {fact["resume_document_id"] for fact in profile["facts"]} == {
        first.json()["resume_document_id"],
        second.json()["resume_document_id"],
    }
    assert activated.status_code == 200
    active_profile = load_evidence_profile(db_session)
    assert active_profile.source_name == "AI产品简历.txt"
    assert all("SQL" not in fact.evidence_text for fact in active_profile.facts)


def test_reviewed_merge_preserves_evidence_and_hides_merged_shell(db_session: Session) -> None:
    organization = Organization(
        canonical_name="合并测试公司",
        normalized_name="合并测试公司",
        official_domain="jobs.merge.example",
        official_domain_verified=True,
        official_domain_source="test-fixture",
    )
    db_session.add(organization)
    db_session.flush()
    left = Opportunity(
        organization_id=organization.id,
        kind=OpportunityKind.POSTING.value,
        display_title="AI 产品经理",
        official_job_id="M-1001",
        review_status="REVIEW",
    )
    right = Opportunity(
        organization_id=organization.id,
        kind=OpportunityKind.POSTING.value,
        display_title="AI产品经理",
        review_status="REVIEW",
    )
    db_session.add_all([left, right])
    db_session.flush()
    _claim(db_session, left.id, "cities", ["上海"])
    _claim(db_session, right.id, "deadline", "2026-09-10")
    verification = VerificationAttempt(
        opportunity_id=right.id,
        result=VerificationResult.OPEN.value,
        evidence_scope=OpportunityKind.POSTING.value,
        verified_domain="jobs.merge.example",
        url="https://jobs.merge.example/M-1001",
        checked_at=datetime.now(timezone.utc),
    )
    candidate = DuplicateCandidate(
        left_opportunity_id=left.id,
        right_opportunity_id=right.id,
        score=0.91,
        features="{}",
        decision="REVIEW",
    )
    db_session.add_all([verification, candidate])
    db_session.commit()

    with _client(db_session) as client:
        merged = client.patch(
            f"/api/opportunities/review/duplicates/{candidate.id}",
            json={"decision": "MERGE", "reason": "人工确认同一官方职位，右侧缺少职位 ID"},
        )
        visible = client.get("/api/opportunities?page_size=100")

    app.dependency_overrides.clear()
    assert merged.status_code == 200
    assert db_session.get(Opportunity, right.id).review_status == "MERGED"
    assert db_session.get(VerificationAttempt, verification.id).opportunity_id == left.id
    moved_deadline = db_session.scalar(
        select(FieldClaim).where(
            FieldClaim.opportunity_id == left.id,
            FieldClaim.field_name == "deadline",
        )
    )
    assert moved_deadline is not None
    assert visible.json()["total"] == 1
