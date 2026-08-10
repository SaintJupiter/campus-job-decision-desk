from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from campus_job_desk.api.app import app
from campus_job_desk.api.serializers import opportunity_list_item
from campus_job_desk.database import get_session
from campus_job_desk.domain.classify import classify_record
from campus_job_desk.domain.enums import (
    Authority,
    Eligibility,
    EvidenceFit,
    OpportunityKind,
    Trust,
    VerificationResult,
)
from campus_job_desk.domain.schemas import CanonicalRecord
from campus_job_desk.models import (
    CampaignPostingLink,
    DataSource,
    DecisionEvent,
    DecisionSnapshot,
    FieldClaim,
    ImportBatch,
    Opportunity,
    OpportunityOrigin,
    Organization,
    ProfileFact,
    RawRecord,
    ShortlistEntry,
    UserPreference,
    VerificationAttempt,
)
from campus_job_desk.services.decision import DecisionService
from campus_job_desk.services.verification import record_verification
from campus_job_desk.services.workflow import (
    build_decision_context,
    decision_is_current,
    decision_rule_version,
    load_evidence_profile,
)


def _raw_origin(
    session: Session,
    opportunity: Opportunity,
    *,
    source_id: str,
    group: str,
    kind: OpportunityKind,
    observed_at: datetime,
    notes: str = "",
) -> RawRecord:
    source = DataSource(
        id=source_id,
        name=source_id,
        kind="SYNTHETIC",
        independence_group=group,
    )
    session.add(source)
    session.flush()
    batch = ImportBatch(
        source_id=source.id,
        file_name=f"{source_id}.csv",
        file_format="CSV",
        file_hash=f"hash-{source_id}",
        mapping_version="v1",
        mapping_json="{}",
        row_count=1,
        success_count=1,
        error_count=0,
        imported_at=observed_at,
    )
    session.add(batch)
    session.flush()
    raw = RawRecord(
        batch_id=batch.id,
        row_number=1,
        row_hash=f"row-{source_id}",
        identity_strength="NONE",
        identity_is_stable=False,
        raw_payload="{}",
        canonical_payload=json.dumps({"notes": notes}, ensure_ascii=False),
        kind_prediction=kind.value,
        kind_confidence=1,
        kind_reasons="[]",
        needs_review=False,
        parse_status="PARSED",
        parse_errors="[]",
        created_at=observed_at,
    )
    session.add(raw)
    session.flush()
    session.add(
        OpportunityOrigin(
            opportunity_id=opportunity.id,
            raw_record_id=raw.id,
        )
    )
    return raw


def _client(session: Session) -> TestClient:
    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def _posting(session: Session, *, kind: OpportunityKind = OpportunityKind.POSTING) -> Opportunity:
    organization = Organization(
        canonical_name="可信测试公司",
        normalized_name="可信测试公司",
        official_domain="careers.trusted.example",
        official_domain_verified=True,
        official_domain_source="test-fixture",
    )
    session.add(organization)
    session.flush()
    opportunity = Opportunity(
        organization_id=organization.id,
        kind=kind.value,
        display_title="AI 产品经理" if kind == OpportunityKind.POSTING else "2027 校园招聘",
        official_job_id="T-1001" if kind == OpportunityKind.POSTING else None,
        review_status="READY",
    )
    session.add(opportunity)
    session.flush()
    return opportunity


def _claim(
    session: Session,
    opportunity_id: str,
    field_name: str,
    value: object,
) -> None:
    session.add(
        FieldClaim(
            opportunity_id=opportunity_id,
            field_name=field_name,
            raw_value=json.dumps(value, ensure_ascii=False),
            normalized_value=json.dumps(value, ensure_ascii=False),
            authority=int(Authority.USER_CONFIRMED),
            observed_at=datetime.now(timezone.utc),
            evidence_label="人工测试证据",
            parser="test-fixture",
            parser_version="v1",
            confidence=1.0,
            selected=True,
        )
    )


def _current_decision(
    session: Session,
    opportunity_id: str,
    *,
    trust: Trust = Trust.VERIFIED,
) -> DecisionSnapshot:
    opportunity = session.get(Opportunity, opportunity_id)
    assert opportunity is not None
    item = DecisionSnapshot(
        opportunity_id=opportunity_id,
        eligibility=Eligibility.PASS.value,
        evidence_fit=EvidenceFit.APPLY.value,
        trust=trust.value,
        reasons="[]",
        unknowns="[]",
        evidence_links="[]",
        rule_version=decision_rule_version(
            load_evidence_profile(session),
            build_decision_context(session, opportunity),
        ),
    )
    session.add(item)
    session.flush()
    return item


def test_unrelated_or_unsupported_page_cannot_become_verified(db_session: Session) -> None:
    posting = _posting(db_session)
    db_session.commit()
    with _client(db_session) as client:
        unrelated = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://unrelated.example/page",
                "evidence_excerpt": "页面显示申请按钮",
            },
        )
        empty_evidence = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "evidence_excerpt": "",
            },
        )
        aggregator = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://offercoming.cn/jobs/T-1001",
                "evidence_excerpt": "聚合页声称仍在招聘",
            },
        )
        copied_job_id = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://evil.example/jobs/T-1001",
                "evidence_excerpt": "伪造页面复制了职位 ID",
            },
        )
    app.dependency_overrides.clear()
    assert unrelated.status_code == 422
    assert empty_evidence.status_code == 422
    assert aggregator.status_code == 422
    assert copied_job_id.status_code == 422
    assert db_session.scalar(select(VerificationAttempt)) is None


def test_wechat_domain_cannot_be_promoted_to_official_open(db_session: Session) -> None:
    posting = _posting(db_session)
    assert posting.organization is not None
    posting.organization.official_domain = "mp.weixin.qq.com"
    posting.official_job_id = None
    db_session.commit()
    with _client(db_session) as client:
        response = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://mp.weixin.qq.com/s/abc123",
                "evidence_excerpt": "公众号文章写着校招已经启动",
            },
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422


def test_unresolved_verification_cannot_write_official_claims(db_session: Session) -> None:
    posting = _posting(db_session)
    db_session.commit()
    with _client(db_session) as client:
        response = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "NOT_FOUND",
                "url": "https://evil.example/random",
                "evidence_excerpt": "无法找到原页面",
                "extracted_fields": {
                    "cities": ["火星"],
                    "graduation_years": ["2099"],
                },
            },
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert db_session.scalar(select(FieldClaim)) is None


def test_verified_page_cannot_inject_protected_identity_or_phishing_url(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    db_session.commit()
    with _client(db_session) as client:
        response = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "evidence_excerpt": "官方页面显示申请按钮可用",
                "extracted_fields": {
                    "company": "Fake Corp",
                    "title": "CEO",
                    "official_job_id": "FAKE",
                    "apply_url": "https://phishing.example/steal",
                },
            },
        )
    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert db_session.scalar(select(FieldClaim)) is None


def test_profile_change_invalidates_old_pass_for_shortlist(db_session: Session) -> None:
    posting = _posting(db_session)
    db_session.add(
        UserPreference(
            key="accepted_cities",
            value='["上海"]',
            hard_constraint=True,
            confirmed=True,
        )
    )
    db_session.add(
        VerificationAttempt(
            opportunity_id=posting.id,
            result=VerificationResult.OPEN.value,
            evidence_scope=OpportunityKind.POSTING.value,
            verified_domain="careers.trusted.example",
            url="https://careers.trusted.example/jobs/T-1001",
            checked_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()
    _current_decision(db_session, posting.id)
    db_session.commit()
    with _client(db_session) as client:
        changed = client.put(
            "/api/workspace/profile/preferences/accepted_cities",
            json={
                "key": "accepted_cities",
                "value": ["北京"],
                "hard_constraint": True,
                "confirmed": True,
            },
        )
        visible = client.get(f"/api/opportunities/{posting.id}")
        filtered = client.get("/api/opportunities?eligibility=PASS")
        dashboard = client.get("/api/workspace/dashboard")
        shortlisted = client.post(f"/api/workspace/shortlist/{posting.id}", json={})
    app.dependency_overrides.clear()
    assert changed.status_code == 200
    assert visible.json()["item"]["decision_current"] is False
    assert visible.json()["item"]["needs_recompute"] is True
    assert visible.json()["item"]["eligibility"] is None
    assert filtered.json()["total"] == 0
    assert dashboard.json()["ready_count"] == 0
    assert db_session.scalar(
        select(DecisionSnapshot.is_current).where(
            DecisionSnapshot.opportunity_id == posting.id
        )
    ) is False
    assert shortlisted.status_code == 409
    assert "重新计算" in shortlisted.json()["detail"]


def test_advisory_preference_does_not_invalidate_unchanged_decision(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    db_session.add(
        VerificationAttempt(
            opportunity_id=posting.id,
            result=VerificationResult.OPEN.value,
            evidence_scope=OpportunityKind.POSTING.value,
            verified_domain="careers.trusted.example",
            url="https://careers.trusted.example/jobs/T-1001",
            checked_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()
    _current_decision(db_session, posting.id)
    db_session.commit()

    with _client(db_session) as client:
        changed = client.put(
            "/api/workspace/profile/preferences/target_role_keywords",
            json={
                "key": "target_role_keywords",
                "value": ["AI产品", "数据产品"],
                "hard_constraint": False,
                "confirmed": True,
            },
        )
        detail = client.get(f"/api/opportunities/{posting.id}")

    app.dependency_overrides.clear()
    assert changed.status_code == 200
    assert detail.json()["item"]["decision_current"] is True
    assert detail.json()["item"]["needs_recompute"] is False
    assert db_session.scalar(
        select(DecisionSnapshot.is_current).where(
            DecisionSnapshot.opportunity_id == posting.id
        )
    ) is True


def test_manual_decision_after_profile_change_recomputes_instead_of_reviving_old_pass(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    db_session.add(
        UserPreference(
            key="accepted_cities",
            value='["上海"]',
            hard_constraint=True,
            confirmed=True,
        )
    )
    _claim(db_session, posting.id, "cities", ["上海"])
    db_session.flush()
    _current_decision(db_session, posting.id)
    db_session.commit()
    with _client(db_session) as client:
        client.put(
            "/api/workspace/profile/preferences/accepted_cities",
            json={
                "key": "accepted_cities",
                "value": ["北京"],
                "hard_constraint": True,
                "confirmed": True,
            },
        )
        manual = client.patch(
            f"/api/opportunities/{posting.id}/decision",
            json={"decision": "HOLD", "reason": "画像变化后重新评估并暂缓"},
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
    app.dependency_overrides.clear()
    assert manual.status_code == 200
    assert detail.json()["item"]["decision_current"] is True
    assert detail.json()["item"]["eligibility"] == Eligibility.FAIL.value
    current_rows = list(
        db_session.scalars(
            select(DecisionSnapshot).where(
                DecisionSnapshot.opportunity_id == posting.id,
                DecisionSnapshot.is_current.is_(True),
            )
        )
    )
    assert len(current_rows) == 1
    assert current_rows[0].manual_decision == "HOLD"


def test_stale_open_or_later_closed_is_not_exported_as_trusted(db_session: Session) -> None:
    posting = _posting(db_session)
    db_session.add(
        VerificationAttempt(
            opportunity_id=posting.id,
            result=VerificationResult.OPEN.value,
            evidence_scope=OpportunityKind.POSTING.value,
            verified_domain="careers.trusted.example",
            url="https://careers.trusted.example/jobs/T-1001",
            checked_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
    )
    db_session.flush()
    _current_decision(db_session, posting.id, trust=Trust.STALE)
    db_session.commit()
    with _client(db_session) as client:
        rejected = client.post(f"/api/workspace/shortlist/{posting.id}", json={})
    app.dependency_overrides.clear()
    assert rejected.status_code == 409
    assert "超过 14 天" in rejected.json()["detail"]

    latest_decision = db_session.scalar(
        select(DecisionSnapshot)
        .where(DecisionSnapshot.opportunity_id == posting.id)
        .order_by(DecisionSnapshot.created_at.desc())
    )
    latest_decision.trust = Trust.VERIFIED.value
    latest_verification = db_session.scalar(select(VerificationAttempt))
    latest_verification.checked_at = datetime.now(timezone.utc)
    db_session.add(ShortlistEntry(opportunity_id=posting.id, note="曾经可投"))
    db_session.commit()
    with _client(db_session) as client:
        closed = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "CLOSED",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "evidence_excerpt": "页面明确显示职位已关闭",
            },
        )
        exported = client.get("/api/workspace/shortlist/export?format=json")
        visible = client.get("/api/workspace/shortlist")
    app.dependency_overrides.clear()
    assert closed.status_code == 201
    assert exported.json() == []
    assert visible.json()[0]["ready"] is False
    assert "最新官网核验不是在招" in visible.json()[0]["blockers"]


def test_fourteen_day_freshness_window_uses_exact_timestamp(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    attempt = VerificationAttempt(
        opportunity_id=posting.id,
        result=VerificationResult.OPEN.value,
        evidence_scope=OpportunityKind.POSTING.value,
        verified_domain="careers.trusted.example",
        url="https://careers.trusted.example/jobs/T-1001",
        checked_at=datetime.now(timezone.utc) - timedelta(days=14, hours=1),
        evidence_excerpt="十四天前的页面曾显示可申请",
    )
    db_session.add(attempt)
    db_session.flush()
    _current_decision(db_session, posting.id, trust=Trust.VERIFIED)
    db_session.commit()

    with _client(db_session) as client:
        detail = client.get(f"/api/opportunities/{posting.id}")
        filtered = client.get("/api/opportunities?trust=VERIFIED")
        shortlisted = client.post(f"/api/workspace/shortlist/{posting.id}", json={})
    app.dependency_overrides.clear()

    assert detail.json()["item"]["decision_current"] is False
    assert detail.json()["item"]["trust"] is None
    assert filtered.json()["total"] == 0
    assert shortlisted.status_code == 409
    assert "超过 14 天" in shortlisted.json()["detail"]


def test_equal_verification_timestamps_have_one_deterministic_latest_state(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    checked_at = datetime.now(timezone.utc).replace(microsecond=0)
    db_session.commit()

    with _client(db_session) as client:
        opened = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "checked_at": checked_at.isoformat(),
                "evidence_excerpt": "页面曾显示可申请",
            },
        )
        closed = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "CLOSED",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "checked_at": checked_at.isoformat(),
                "evidence_excerpt": "随后页面明确显示职位已关闭",
            },
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
        open_filter = client.get("/api/opportunities?verification=OPEN")
        closed_filter = client.get("/api/opportunities?verification=CLOSED")
    app.dependency_overrides.clear()

    assert opened.status_code == 201
    assert closed.status_code == 201
    assert detail.json()["item"]["verification"] == "CLOSED"
    assert open_filter.json()["total"] == 0
    assert closed_filter.json()["total"] == 1


def test_newer_claim_from_same_official_source_supersedes_old_value(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    now = datetime.now(timezone.utc)
    db_session.commit()

    with _client(db_session) as client:
        first = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "checked_at": (now - timedelta(days=2)).isoformat(),
                "evidence_excerpt": "页面当时显示工作城市为上海",
                "extracted_fields": {"cities": ["上海"]},
            },
        )
        second = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "checked_at": (now - timedelta(days=1)).isoformat(),
                "evidence_excerpt": "页面更新后工作城市改为杭州",
                "extracted_fields": {"cities": ["杭州"]},
            },
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
    app.dependency_overrides.clear()

    assert first.status_code == 201
    assert second.status_code == 201
    body = detail.json()
    assert body["item"]["cities"] == ["杭州"]
    assert body["item"]["conflict_count"] == 0
    assert body["item"]["historical_difference_count"] == 1
    city_claims = [
        claim for claim in body["claims"] if claim["field_name"] == "cities"
    ]
    assert sum(claim["selected"] for claim in city_claims) == 1
    old_claim = next(claim for claim in city_claims if claim["normalized_value"] == ["上海"])
    assert "较新 claim" in old_claim["resolution_reason"]


def test_verification_timestamps_are_canonicalized_to_utc_before_sorting(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    newer_utc = datetime(2026, 8, 9, 17, 42, tzinfo=timezone.utc)
    older_local = datetime.fromisoformat("2026-08-10T00:42:00+08:00")
    assert newer_utc > older_local.astimezone(timezone.utc)
    db_session.commit()

    with _client(db_session) as client:
        newer = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "checked_at": newer_utc.isoformat(),
                "evidence_excerpt": "实际较新的官网页面显示仍可申请",
                "extracted_fields": {"cities": ["上海"]},
            },
        )
        older = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "CLOSED",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "checked_at": older_local.isoformat(),
                "evidence_excerpt": "不同时区下实际更旧的页面显示关闭",
                "extracted_fields": {"cities": ["杭州"]},
            },
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
    app.dependency_overrides.clear()

    assert newer.status_code == 201
    assert older.status_code == 201
    assert detail.json()["item"]["verification"] == "OPEN"
    assert detail.json()["item"]["cities"] == ["上海"]
    assert detail.json()["verifications"][0]["checked_at"].startswith(
        "2026-08-09T17:42:00"
    )


def test_campaign_claim_uses_campaign_authority(db_session: Session) -> None:
    campaign = _posting(db_session, kind=OpportunityKind.CAMPAIGN)
    record_verification(
        db_session,
        opportunity_id=campaign.id,
        result=VerificationResult.OPEN,
        url="https://careers.trusted.example/campus",
        evidence_excerpt="官网校园招聘页面仍开放",
        extracted_fields={"cities": ["上海", "杭州"]},
    )
    db_session.commit()
    authorities = set(
        db_session.scalars(
            select(FieldClaim.authority).where(FieldClaim.opportunity_id == campaign.id)
        )
    )
    assert authorities == {int(Authority.OFFICIAL_CAMPAIGN)}


def test_campaign_verification_never_becomes_posting_verification_after_reclass(
    db_session: Session,
) -> None:
    campaign = _posting(db_session, kind=OpportunityKind.CAMPAIGN)
    db_session.commit()
    with _client(db_session) as client:
        verified = client.post(
            f"/api/opportunities/{campaign.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/campus",
                "evidence_excerpt": "官网校园招聘项目总页仍在开放",
            },
        )
        reclassified = client.patch(
            f"/api/opportunities/{campaign.id}/classification",
            json={"kind": "POSTING", "reason": "人工确认需要改为具体岗位进一步复核"},
        )
        detail = client.get(f"/api/opportunities/{campaign.id}")
        shortlisted = client.post(f"/api/workspace/shortlist/{campaign.id}", json={})
    app.dependency_overrides.clear()
    assert verified.status_code == 201
    assert verified.json()["evidence_scope"] == "CAMPAIGN"
    assert reclassified.status_code == 200
    assert detail.json()["item"]["verification"] is None
    assert detail.json()["item"]["trust"] not in {
        Trust.VERIFIED.value,
        Trust.VERIFIED_WITH_CONFLICT.value,
    }
    assert shortlisted.status_code == 409


def test_same_independence_group_counts_as_one_source(db_session: Session) -> None:
    posting = _posting(db_session)
    for index in (1, 2):
        source = DataSource(
            id=f"same-vendor-{index}",
            name=f"同一供应商入口 {index}",
            kind="PAID_TABLE",
            independence_group="same-vendor",
        )
        db_session.add(source)
        db_session.flush()
        batch = ImportBatch(
            source_id=source.id,
            file_name=f"source-{index}.csv",
            file_format="csv",
            file_hash=f"{'a' if index == 1 else 'b'}" * 64,
            mapping_version="test",
            mapping_json="{}",
            row_count=1,
            success_count=1,
            error_count=0,
        )
        db_session.add(batch)
        db_session.flush()
        raw = RawRecord(
            batch_id=batch.id,
            row_number=1,
            row_hash=f"{'c' if index == 1 else 'd'}" * 64,
            identity_strength="COMPOUND_HINT",
            identity_is_stable=False,
            raw_payload="{}",
            canonical_payload=CanonicalRecord(
                company="可信测试公司",
                title="AI 产品经理",
            ).model_dump_json(),
            kind_prediction="POSTING",
            kind_confidence=0.6,
            kind_reasons="[]",
            needs_review=True,
            parse_status="PARSED",
            parse_errors="[]",
        )
        db_session.add(raw)
        db_session.flush()
        db_session.add(
            OpportunityOrigin(opportunity_id=posting.id, raw_record_id=raw.id)
        )
    db_session.commit()
    context = build_decision_context(db_session, posting)
    assert context.source_count == 1


def test_wechat_announcement_is_not_confident_specific_posting() -> None:
    prediction = classify_record(
        CanonicalRecord(
            company="某科技公司",
            title="AI产品经理",
            cities=["上海"],
            announcement_url="https://mp.weixin.qq.com/s/abc123",
        )
    )
    assert prediction.needs_review is True
    assert prediction.confidence < 0.8


def test_profile_delete_removes_personal_events_and_manual_edit_changes_provenance(
    db_session: Session,
) -> None:
    fact = ProfileFact(
        category="EDUCATION",
        label="硕士",
        value="硕士",
        evidence_text="教育：硕士",
        evidence_start=0,
        evidence_end=5,
        provenance=json.dumps(
            {
                "source_type": "resume",
                "source_name": "private-resume.pdf",
                "extraction_method": "fixture",
            }
        ),
        confirmed=False,
    )
    db_session.add(fact)
    db_session.commit()
    with _client(db_session) as client:
        edited = client.patch(
            f"/api/workspace/profile/facts/{fact.id}",
            json={"value": "博士", "confirmed": True},
        )
        deleted = client.delete("/api/workspace/profile")
    app.dependency_overrides.clear()
    assert edited.status_code == 200
    assert deleted.status_code == 204
    assert db_session.scalar(select(ProfileFact)) is None
    personal_events = list(
        db_session.scalars(
            select(DecisionEvent).where(
                DecisionEvent.entity_type.in_(("profile", "profile_fact", "preference"))
            )
        )
    )
    assert len(personal_events) == 1
    assert "博士" not in personal_events[0].payload


def test_unconfirmed_imported_domain_cannot_anchor_official_verification(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    assert posting.organization is not None
    posting.organization.official_domain = "evil.example"
    posting.organization.candidate_domain = "evil.example"
    posting.organization.official_domain_verified = False
    db_session.commit()
    with _client(db_session) as client:
        rejected = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://evil.example/jobs/T-1001",
                "evidence_excerpt": "伪造页面声称岗位开放",
            },
        )
        aggregator = client.patch(
            f"/api/opportunities/{posting.id}/official-domain",
            json={"domain": "offercoming.cn:443", "reason": "用户手动测试聚合域"},
        )
        confirmed = client.patch(
            f"/api/opportunities/{posting.id}/official-domain",
            json={
                "domain": "https://careers.trusted-company.com/campus",
                "reason": "用户在公司主站确认了招聘子域",
            },
        )
        accepted = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted-company.com:443/jobs/T-1001",
                "evidence_excerpt": "官网岗位页显示申请按钮可用",
            },
        )
    app.dependency_overrides.clear()
    assert rejected.status_code == 422
    assert aggregator.status_code == 422
    assert confirmed.status_code == 200
    assert accepted.status_code == 201
    assert posting.organization.official_domain == "careers.trusted-company.com"
    assert posting.organization.official_domain_verified is True


def test_public_suffix_ip_and_shared_host_cannot_be_trust_anchor(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    db_session.commit()
    responses = []
    with _client(db_session) as client:
        for domain in ("com", "cn", "co.uk", "127.0.0.1", "github.io"):
            responses.append(
                client.patch(
                    f"/api/opportunities/{posting.id}/official-domain",
                    json={"domain": domain, "reason": "安全边界回归测试"},
                )
            )
    app.dependency_overrides.clear()
    assert {response.status_code for response in responses} == {422}


def test_posting_requires_direct_job_page_not_campaign_landing_page(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    posting.official_job_id = None
    db_session.commit()
    with _client(db_session) as client:
        broad = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/campus/2027",
                "evidence_excerpt": "校园招聘项目总页仍然开放",
            },
        )
        disguised_broad = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/2027",
                "evidence_excerpt": "这仍是校园招聘项目总页",
            },
        )
        unbound_specific = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/ABCD1234",
                "evidence_excerpt": "具体岗位页显示申请按钮可用",
            },
        )
        year_identity = client.patch(
            f"/api/opportunities/{posting.id}/official-identity",
            json={
                "official_job_id": "2027",
                "url": "https://careers.trusted.example/jobs/2027",
                "reason": "年份不能作为具体岗位身份",
            },
        )
        campaign_identity = client.patch(
            f"/api/opportunities/{posting.id}/official-identity",
            json={
                "official_job_id": "campus-2027",
                "url": "https://careers.trusted.example/jobs/campus-2027",
                "reason": "招聘项目组合词不能作为具体岗位身份",
            },
        )
        identity = client.patch(
            f"/api/opportunities/{posting.id}/official-identity",
            json={
                "official_job_id": "ABCD1234",
                "url": "https://careers.trusted.example/jobs/ABCD1234",
                "reason": "URL 路径和页面岗位 ID 一致",
            },
        )
        specific = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/ABCD1234",
                "evidence_excerpt": "具体岗位页显示申请按钮可用",
            },
        )
    app.dependency_overrides.clear()
    assert broad.status_code == 422
    assert disguised_broad.status_code == 422
    assert unbound_specific.status_code == 422
    assert year_identity.status_code == 422
    assert campaign_identity.status_code == 422
    assert identity.status_code == 200
    assert specific.status_code == 201


def test_fresh_open_check_does_not_revive_expired_eligibility_claims(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    observed_at = datetime.now(timezone.utc) - timedelta(days=365)
    raw = _raw_origin(
        db_session,
        posting,
        source_id="expired-source",
        group="expired-source",
        kind=OpportunityKind.POSTING,
        observed_at=observed_at,
    )
    for field_name, value in (
        ("cities", ["上海"]),
        ("graduation_years", ["2027"]),
        ("education", ["本科及以上"]),
        ("recruitment_type", "秋招"),
    ):
        db_session.add(
            FieldClaim(
                opportunity_id=posting.id,
                raw_record_id=raw.id,
                field_name=field_name,
                raw_value=json.dumps(value, ensure_ascii=False),
                normalized_value=json.dumps(value, ensure_ascii=False),
                authority=int(Authority.AGGREGATOR),
                observed_at=observed_at,
                evidence_label="一年前的供应商表",
                parser="test-fixture",
                parser_version="v1",
                confidence=1,
                selected=True,
            )
        )
    _claim(db_session, posting.id, "title", "AI 产品经理")
    for category, value, evidence in (
        ("GRADUATION_YEAR", "2027", "预计 2027 年毕业"),
        ("EDUCATION", "硕士", "硕士研究生在读"),
    ):
        db_session.add(
            ProfileFact(
                category=category,
                label=value,
                value=value,
                evidence_text=evidence,
                evidence_start=0,
                evidence_end=len(evidence),
                provenance=json.dumps({"source_type": "resume"}),
                confirmed=True,
            )
        )
    for key, value in (
        ("accepted_cities", ["上海"]),
        ("accepted_recruitment_types", ["校招"]),
    ):
        db_session.add(
            UserPreference(
                key=key,
                value=json.dumps(value, ensure_ascii=False),
                hard_constraint=True,
                confirmed=True,
            )
        )
    record_verification(
        db_session,
        opportunity_id=posting.id,
        result=VerificationResult.OPEN,
        url="https://careers.trusted.example/jobs/T-1001",
        evidence_excerpt="具体岗位页面显示仍在接受申请",
    )
    db_session.commit()

    with _client(db_session) as client:
        recomputed = client.post(
            "/api/workspace/decisions/recompute",
            json={"opportunity_ids": [posting.id]},
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
        shortlisted = client.post(f"/api/workspace/shortlist/{posting.id}", json={})
    app.dependency_overrides.clear()

    context = build_decision_context(db_session, posting)
    assert recomputed.status_code == 200
    assert context.record.cities == []
    assert context.record.graduation_years == []
    assert detail.json()["item"]["eligibility"] == Eligibility.UNKNOWN.value
    assert detail.json()["item"]["trust"] == Trust.VERIFIED.value
    assert shortlisted.status_code == 409


def test_fresh_open_check_does_not_revive_expired_official_field_claims(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    observed_at = datetime.now(timezone.utc) - timedelta(days=365)
    record_verification(
        db_session,
        opportunity_id=posting.id,
        result=VerificationResult.OPEN,
        url="https://careers.trusted.example/jobs/T-1001",
        checked_at=observed_at,
        evidence_excerpt="旧官网岗位页当时显示接受申请",
        extracted_fields={
            "cities": ["上海"],
            "graduation_years": ["2027"],
            "education": ["本科及以上"],
            "recruitment_type": "秋招",
        },
    )
    _claim(db_session, posting.id, "title", "AI 产品经理")
    for category, value, evidence in (
        ("GRADUATION_YEAR", "2027", "预计 2027 年毕业"),
        ("EDUCATION", "硕士", "硕士研究生在读"),
    ):
        db_session.add(
            ProfileFact(
                category=category,
                label=value,
                value=value,
                evidence_text=evidence,
                evidence_start=0,
                evidence_end=len(evidence),
                provenance=json.dumps({"source_type": "resume"}),
                confirmed=True,
            )
        )
    for key, value in (
        ("accepted_cities", ["上海"]),
        ("accepted_recruitment_types", ["校招"]),
    ):
        db_session.add(
            UserPreference(
                key=key,
                value=json.dumps(value, ensure_ascii=False),
                hard_constraint=True,
                confirmed=True,
            )
        )
    record_verification(
        db_session,
        opportunity_id=posting.id,
        result=VerificationResult.OPEN,
        url="https://careers.trusted.example/jobs/T-1001",
        evidence_excerpt="今日具体岗位页只确认仍在接受申请",
    )
    db_session.commit()

    with _client(db_session) as client:
        client.post(
            "/api/workspace/decisions/recompute",
            json={"opportunity_ids": [posting.id]},
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
        shortlisted = client.post(f"/api/workspace/shortlist/{posting.id}", json={})
    app.dependency_overrides.clear()

    context = build_decision_context(db_session, posting)
    assert context.record.cities == []
    assert context.record.graduation_years == []
    assert detail.json()["item"]["eligibility"] == Eligibility.UNKNOWN.value
    assert detail.json()["item"]["trust"] == Trust.VERIFIED.value
    assert shortlisted.status_code == 409


def test_official_identity_is_unique_case_insensitively_within_company(
    db_session: Session,
) -> None:
    existing = _posting(db_session)
    assert existing.organization is not None
    other = Opportunity(
        organization_id=existing.organization_id,
        kind=OpportunityKind.POSTING.value,
        display_title="数据产品经理",
        official_job_id=None,
        review_status="READY",
    )
    db_session.add(other)
    db_session.commit()

    with _client(db_session) as client:
        response = client.patch(
            f"/api/opportunities/{other.id}/official-identity",
            json={
                "official_job_id": "t-1001",
                "url": "https://careers.trusted.example/jobs/t-1001",
                "reason": "尝试绑定大小写不同但相同的官方岗位 ID",
            },
        )
    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert other.official_job_id is None


def test_job_id_in_unrelated_query_text_does_not_make_campaign_page_specific(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    db_session.commit()
    with _client(db_session) as client:
        ref_attack = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/campus/2027?ref=T-1001",
                "evidence_excerpt": "岗位 ID 只出现在无关 ref 参数中",
            },
        )
        note_attack = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/join-us?note=fooT-1001bar",
                "evidence_excerpt": "岗位 ID 只是无关备注文本的子串",
            },
        )
        path_attack = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/campus/T-1001/overview",
                "evidence_excerpt": "岗位 ID 位于招聘项目路径而非具体岗位容器下",
            },
        )
        explicit_query = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/job-detail?jobId=T-1001",
                "evidence_excerpt": "明确 jobId 参数精确对应当前岗位",
            },
        )
        generic_id_attacks = [
            client.post(
                f"/api/opportunities/{posting.id}/verifications",
                json={
                    "result": "OPEN",
                    "url": f"https://careers.trusted.example{path}?id=T-1001",
                    "evidence_excerpt": "同域普通页面不能仅凭通用 id 参数成为岗位页",
                },
            )
            for path in ("/news", "/campus", "/about")
        ]
        generic_detail_attacks = [
            client.post(
                f"/api/opportunities/{posting.id}/verifications",
                json={
                    "result": "OPEN",
                    "url": f"https://careers.trusted.example{path}",
                    "evidence_excerpt": "裸 detail 路径缺少具体岗位上下文",
                },
            )
            for path in ("/news/detail/T-1001", "/campus/detail/T-1001")
        ]
    app.dependency_overrides.clear()
    assert ref_attack.status_code == 422
    assert note_attack.status_code == 422
    assert path_attack.status_code == 422
    assert {response.status_code for response in generic_id_attacks} == {422}
    assert {response.status_code for response in generic_detail_attacks} == {422}
    assert explicit_query.status_code == 201


def test_other_job_page_from_same_company_cannot_verify_current_posting(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    posting.official_job_id = "B-2002"
    db_session.commit()
    with _client(db_session) as client:
        wrong_job = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/A-1001",
                "evidence_excerpt": "这是同公司的另一个具体岗位页",
            },
        )
    app.dependency_overrides.clear()
    assert wrong_job.status_code == 422
    assert db_session.scalar(select(VerificationAttempt)) is None


def test_verified_parent_domain_accepts_specific_recruiting_subdomain(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    assert posting.organization is not None
    posting.organization.official_domain = "trusted-company.com"
    posting.organization.official_domain_verified = True
    db_session.commit()
    with _client(db_session) as client:
        opened = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://jobs.trusted-company.com/jobs/T-1001",
                "evidence_excerpt": "招聘子域的具体岗位页显示可申请",
            },
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
    app.dependency_overrides.clear()
    assert opened.status_code == 201
    assert opened.json()["verified_domain"] == "trusted-company.com"
    assert detail.json()["item"]["verification"] == VerificationResult.OPEN.value


def test_changing_trust_anchor_invalidates_old_domain_verification(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    db_session.commit()
    with _client(db_session) as client:
        opened = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "evidence_excerpt": "旧官方域名下的具体岗位页可申请",
            },
        )
        changed = client.patch(
            f"/api/opportunities/{posting.id}/official-domain",
            json={
                "domain": "careers.new-trusted-company.com",
                "reason": "公司主站已迁移到新招聘域名",
            },
        )
        client.post(
            "/api/workspace/decisions/recompute",
            json={"opportunity_ids": [posting.id]},
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
        shortlisted = client.post(f"/api/workspace/shortlist/{posting.id}", json={})
    app.dependency_overrides.clear()
    assert opened.status_code == 201
    assert changed.status_code == 200
    assert detail.json()["item"]["verification"] is None
    assert detail.json()["item"]["trust"] not in {
        Trust.VERIFIED.value,
        Trust.VERIFIED_WITH_CONFLICT.value,
    }
    assert shortlisted.status_code == 409


def test_campaign_fields_do_not_leak_into_posting_after_reclassification(
    db_session: Session,
) -> None:
    campaign = _posting(db_session, kind=OpportunityKind.CAMPAIGN)
    db_session.commit()
    with _client(db_session) as client:
        client.post(
            f"/api/opportunities/{campaign.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/campus",
                "evidence_excerpt": "项目总页显示 2027 届上海校招开放",
                "extracted_fields": {
                    "cities": ["上海"],
                    "graduation_years": ["2027届"],
                },
            },
        )
        client.patch(
            f"/api/opportunities/{campaign.id}/classification",
            json={"kind": "POSTING", "reason": "人工确认为具体岗位但需重新核验"},
        )
        identity = client.patch(
            f"/api/opportunities/{campaign.id}/official-identity",
            json={
                "official_job_id": "ABCD1234",
                "url": "https://careers.trusted.example/jobs/ABCD1234",
                "reason": "URL 路径和页面岗位 ID 一致",
            },
        )
        opened = client.post(
            f"/api/opportunities/{campaign.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/ABCD1234",
                "evidence_excerpt": "具体岗位页只能确认岗位仍然开放",
            },
        )
        detail = client.get(f"/api/opportunities/{campaign.id}")
        city_filter = client.get("/api/opportunities?city=上海")
    app.dependency_overrides.clear()
    assert identity.status_code == 200
    assert opened.status_code == 201
    assert detail.json()["item"]["cities"] == []
    assert detail.json()["item"]["graduation_years"] == []
    assert detail.json()["item"]["eligibility"] == Eligibility.UNKNOWN.value
    assert city_filter.json()["total"] == 0
    historical_city_claims = [
        claim
        for claim in detail.json()["claims"]
        if claim["field_name"] == "cities"
    ]
    assert historical_city_claims
    assert all(claim["applicable"] is False for claim in historical_city_claims)
    assert all(claim["selected"] is False for claim in historical_city_claims)


def test_reclassifying_posting_to_campaign_retires_specific_job_identity(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    posting.canonical_key = "official-job:可信测试公司:t-1001"
    db_session.commit()

    with _client(db_session) as client:
        changed = client.patch(
            f"/api/opportunities/{posting.id}/classification",
            json={"kind": "CAMPAIGN", "reason": "实际是招聘项目总线索"},
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
    app.dependency_overrides.clear()

    assert changed.status_code == 200
    assert posting.official_job_id is None
    assert posting.canonical_key is not None
    assert posting.canonical_key.startswith("campaign:")
    assert detail.json()["item"]["official_job_id"] is None


def test_retired_identity_does_not_revive_after_classification_round_trip(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    posting.official_job_id = None
    db_session.commit()

    with _client(db_session) as client:
        first = client.patch(
            f"/api/opportunities/{posting.id}/official-identity",
            json={
                "official_job_id": "J-1001",
                "url": "https://careers.trusted.example/jobs/J-1001",
                "reason": "首次绑定具体岗位身份",
            },
        )
        client.patch(
            f"/api/opportunities/{posting.id}/classification",
            json={"kind": "CAMPAIGN", "reason": "发现其实是招聘项目"},
        )
        client.patch(
            f"/api/opportunities/{posting.id}/classification",
            json={"kind": "POSTING", "reason": "随后找到另一具体岗位"},
        )
        second = client.patch(
            f"/api/opportunities/{posting.id}/official-identity",
            json={
                "official_job_id": "J-2002",
                "url": "https://careers.trusted.example/jobs/J-2002",
                "reason": "重新绑定当前具体岗位身份",
            },
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
    app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert detail.json()["item"]["official_job_id"] == "j-2002"
    identity_claims = [
        claim
        for claim in detail.json()["claims"]
        if claim["field_name"] == "official_job_id"
    ]
    assert sum(claim["selected"] for claim in identity_claims) == 1
    selected = next(claim for claim in identity_claims if claim["selected"])
    assert selected["normalized_value"] == "j-2002"
    retired = next(
        claim for claim in identity_claims if claim["normalized_value"] == "j-1001"
    )
    assert retired["applicable"] is False


def test_shared_ats_scope_rejects_another_company_tenant(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    posting.organization.official_domain = "job-boards.greenhouse.io"
    posting.organization.official_scope_path = "/company-a"
    db_session.commit()

    with _client(db_session) as client:
        response = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://job-boards.greenhouse.io/company-b/jobs/T-1001",
                "evidence_excerpt": "页面显示该岗位当前接受申请",
            },
        )
    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "租户" in response.json()["detail"] or "路径" in response.json()["detail"]


def test_shared_ats_confirmation_requires_and_persists_tenant_path(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    posting.organization.official_domain = ""
    posting.organization.official_domain_verified = False
    db_session.commit()

    with _client(db_session) as client:
        host_only = client.patch(
            f"/api/opportunities/{posting.id}/official-domain",
            json={
                "domain": "job-boards.greenhouse.io",
                "reason": "公司官网跳转到该 ATS",
            },
        )
        scoped = client.patch(
            f"/api/opportunities/{posting.id}/official-domain",
            json={
                "domain": "https://job-boards.greenhouse.io/company-a/jobs",
                "reason": "公司官网跳转到该租户招聘页",
            },
        )
    app.dependency_overrides.clear()

    assert host_only.status_code == 422
    assert scoped.status_code == 200
    assert posting.organization.official_domain == "job-boards.greenhouse.io"
    assert posting.organization.official_scope_path == "/company-a"


def test_shared_ats_parent_domain_cannot_bypass_tenant_scope(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    posting.organization.official_domain = ""
    posting.organization.official_domain_verified = False
    db_session.commit()

    with _client(db_session) as client:
        response = client.patch(
            f"/api/opportunities/{posting.id}/official-domain",
            json={
                "domain": "greenhouse.io",
                "reason": "不能把共享服务父域当作单家公司官网",
            },
        )
    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "共享 ATS" in response.json()["detail"]


def test_workday_infrastructure_domains_cannot_be_company_trust_anchors(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    posting.organization.official_domain = ""
    posting.organization.official_domain_verified = False
    db_session.commit()

    with _client(db_session) as client:
        parent = client.patch(
            f"/api/opportunities/{posting.id}/official-domain",
            json={"domain": "myworkdayjobs.com", "reason": "共享 ATS 父域"},
        )
        infrastructure = client.patch(
            f"/api/opportunities/{posting.id}/official-domain",
            json={"domain": "wd5.myworkdayjobs.com", "reason": "共享 ATS 层级域"},
        )
    app.dependency_overrides.clear()

    assert parent.status_code == 422
    assert infrastructure.status_code == 422
    assert "共享 ATS" in parent.json()["detail"]
    assert "共享 ATS" in infrastructure.json()["detail"]


def test_campaign_link_requires_same_company_and_is_retired_on_reclassification(
    db_session: Session,
) -> None:
    campaign = _posting(db_session, kind=OpportunityKind.CAMPAIGN)
    other_company = Organization(
        canonical_name="另一家公司",
        normalized_name="另一家公司",
        official_domain="careers.other.example",
        official_domain_verified=True,
        official_domain_source="test-fixture",
    )
    db_session.add(other_company)
    db_session.flush()
    other_company_posting = Opportunity(
        organization_id=other_company.id,
        kind=OpportunityKind.POSTING.value,
        display_title="AI 产品经理",
        official_job_id="OTHER-1001",
        review_status="READY",
    )
    db_session.add(other_company_posting)
    db_session.commit()

    with _client(db_session) as client:
        cross_company = client.post(
            f"/api/opportunities/{campaign.id}/postings",
            json={
                "posting_id": other_company_posting.id,
                "evidence": "人工检查官网层级",
                "confidence": 1,
            },
        )
    app.dependency_overrides.clear()
    assert cross_company.status_code == 422

    same_company_posting = Opportunity(
        organization_id=campaign.organization_id,
        kind=OpportunityKind.POSTING.value,
        display_title="AI 产品经理",
        official_job_id="P-2002",
        review_status="READY",
    )
    db_session.add(same_company_posting)
    db_session.flush()
    db_session.add(
        CampaignPostingLink(
            campaign_id=campaign.id,
            posting_id=same_company_posting.id,
            evidence="同公司官网岗位页",
            confidence=1,
            confirmed_by_user=True,
        )
    )
    _raw_origin(
        db_session,
        campaign,
        source_id="campaign-source",
        group="campaign-source",
        kind=OpportunityKind.CAMPAIGN,
        observed_at=datetime.now(timezone.utc),
        notes="招聘项目线索，不是具体岗位 JD",
    )
    db_session.commit()

    with _client(db_session) as client:
        changed = client.patch(
            f"/api/opportunities/{campaign.id}/classification",
            json={"kind": "POSTING", "reason": "确认需要按具体岗位重新建证据"},
        )
    app.dependency_overrides.clear()

    assert changed.status_code == 200
    assert db_session.get(
        CampaignPostingLink,
        (campaign.id, same_company_posting.id),
    ) is None
    context = build_decision_context(db_session, campaign)
    assert context.record.title == ""
    assert context.record.notes == ""
    item = opportunity_list_item(db_session, campaign)
    assert item.title == ""
    from campus_job_desk.api.routes.workspace import _shortlist_readiness

    ready, blockers = _shortlist_readiness(db_session, campaign)
    assert ready is False
    assert any("缺少具体岗位名称" in blocker for blocker in blockers)


def test_old_official_domain_claims_do_not_conflict_with_current_domain(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    record_verification(
        db_session,
        opportunity_id=posting.id,
        result=VerificationResult.OPEN,
        url="https://careers.trusted.example/jobs/T-1001",
        evidence_excerpt="页面显示该岗位正在接受申请",
        extracted_fields={"cities": ["上海"]},
    )
    posting.organization.official_domain = "jobs.current.example"
    posting.organization.official_domain_verified = True
    record_verification(
        db_session,
        opportunity_id=posting.id,
        result=VerificationResult.OPEN,
        url="https://jobs.current.example/jobs/T-1001",
        evidence_excerpt="页面显示该岗位正在接受申请",
        extracted_fields={"cities": ["北京"]},
    )
    db_session.flush()

    context = build_decision_context(db_session, posting)
    assert context.record.cities == ["北京"]
    assert "cities" not in context.conflicting_fields
    old_city = db_session.scalar(
        select(FieldClaim)
        .join(VerificationAttempt, VerificationAttempt.id == FieldClaim.verification_id)
        .where(
            FieldClaim.opportunity_id == posting.id,
            FieldClaim.field_name == "cities",
            VerificationAttempt.verified_domain == "careers.trusted.example",
        )
    )
    assert old_city is not None
    assert old_city.selected is False


def test_consistent_decision_expires_when_source_evidence_becomes_stale(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    observed_at = datetime.now(timezone.utc) - timedelta(days=15)
    for index in range(2):
        raw = _raw_origin(
            db_session,
            posting,
            source_id=f"old-source-{index}",
            group=f"old-source-{index}",
            kind=OpportunityKind.POSTING,
            observed_at=observed_at,
        )
        db_session.add(
            FieldClaim(
                opportunity_id=posting.id,
                raw_record_id=raw.id,
                field_name="title",
                raw_value=json.dumps("AI 产品经理", ensure_ascii=False),
                normalized_value=json.dumps("ai 产品经理", ensure_ascii=False),
                authority=int(Authority.AGGREGATOR),
                observed_at=observed_at,
                evidence_label=f"旧来源 {index}",
                parser="test-fixture",
                parser_version="v1",
                confidence=1,
                selected=index == 0,
            )
        )
    db_session.flush()
    snapshot = DecisionSnapshot(
        opportunity_id=posting.id,
        eligibility=Eligibility.UNKNOWN.value,
        evidence_fit=EvidenceFit.UNKNOWN.value,
        trust=Trust.CONSISTENT.value,
        reasons="[]",
        unknowns="[]",
        evidence_links="[]",
        rule_version=decision_rule_version(
            load_evidence_profile(db_session),
            build_decision_context(db_session, posting),
        ),
        is_current=True,
    )
    db_session.add(snapshot)
    db_session.flush()

    assert decision_is_current(db_session, snapshot) is False


def test_one_fresh_source_does_not_reactivate_an_expired_second_source(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    now = datetime.now(timezone.utc)
    for source_id, observed_at, selected in (
        ("old-source", now - timedelta(days=365), False),
        ("fresh-source", now, True),
    ):
        raw = _raw_origin(
            db_session,
            posting,
            source_id=source_id,
            group=source_id,
            kind=OpportunityKind.POSTING,
            observed_at=observed_at,
        )
        db_session.add(
            FieldClaim(
                opportunity_id=posting.id,
                raw_record_id=raw.id,
                field_name="title",
                raw_value=json.dumps("AI 产品经理", ensure_ascii=False),
                normalized_value=json.dumps("ai 产品经理", ensure_ascii=False),
                authority=int(Authority.AGGREGATOR),
                observed_at=observed_at,
                evidence_label=source_id,
                parser="test-fixture",
                parser_version="v1",
                confidence=1,
                selected=selected,
            )
        )
    db_session.flush()

    context = build_decision_context(db_session, posting)
    trust = DecisionService().evaluate_trust(context).result

    assert context.source_count == 1
    assert trust == Trust.UNKNOWN


def test_posting_round_trip_cannot_revive_old_official_verification(
    db_session: Session,
) -> None:
    posting = _posting(db_session)
    _claim(db_session, posting.id, "cities", ["上海"])
    _claim(db_session, posting.id, "graduation_years", ["2027"])
    db_session.commit()

    with _client(db_session) as client:
        opened = client.post(
            f"/api/opportunities/{posting.id}/verifications",
            json={
                "result": "OPEN",
                "url": "https://careers.trusted.example/jobs/T-1001",
                "evidence_excerpt": "具体岗位页面显示正在接受申请",
            },
        )
        client.patch(
            f"/api/opportunities/{posting.id}/classification",
            json={"kind": "CAMPAIGN", "reason": "发现原记录是招聘项目"},
        )
        client.patch(
            f"/api/opportunities/{posting.id}/classification",
            json={"kind": "POSTING", "reason": "重新建立具体岗位记录"},
        )
        client.post(
            "/api/workspace/decisions/recompute",
            json={"opportunity_ids": [posting.id]},
        )
        detail = client.get(f"/api/opportunities/{posting.id}")
        shortlisted = client.post(f"/api/workspace/shortlist/{posting.id}", json={})
    app.dependency_overrides.clear()

    assert opened.status_code == 201
    assert detail.json()["item"]["official_job_id"] is None
    assert detail.json()["item"]["verification"] is None
    assert detail.json()["item"]["trust"] not in {
        Trust.VERIFIED.value,
        Trust.VERIFIED_WITH_CONFLICT.value,
    }
    assert shortlisted.status_code == 409
