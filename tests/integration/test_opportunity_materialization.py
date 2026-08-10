from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from campus_job_desk.api.serializers import opportunity_list_item
from campus_job_desk.domain.enums import DuplicateDecision, OpportunityKind, SourceKind
from campus_job_desk.ingest.adapters import parse_snapshot
from campus_job_desk.models import (
    CampaignPostingLink,
    DuplicateCandidate,
    FieldClaim,
    Opportunity,
    OpportunityOrigin,
    RawRecord,
)
from campus_job_desk.repositories.imports import import_parsed_snapshot
from campus_job_desk.services.materialization import materialize_batch

ROOT = Path(__file__).resolve().parents[2]


def _import_demo(
    db_session: Session,
    file_name: str,
    *,
    source_id: str,
    source_name: str,
    source_kind: SourceKind = SourceKind.SYNTHETIC,
) -> str:
    snapshot = parse_snapshot(
        ROOT / "data/demo" / file_name,
        source_name=source_name,
        source_kind=source_kind,
    )
    result = import_parsed_snapshot(
        db_session,
        snapshot,
        source_id=source_id,
        independence_group=source_id,
    )
    return result.batch_id


def test_materializes_sources_into_canonical_opportunities_with_full_provenance(
    db_session: Session,
) -> None:
    alpha_id = _import_demo(
        db_session,
        "source_alpha.csv",
        source_id="alpha",
        source_name="供应商甲",
    )
    beta_id = _import_demo(
        db_session,
        "source_beta.tsv",
        source_id="beta",
        source_name="供应商乙",
    )

    alpha = materialize_batch(db_session, alpha_id)
    beta = materialize_batch(db_session, beta_id)

    assert alpha.created_opportunities == 5
    assert beta.created_opportunities == 2
    assert beta.reused_opportunities == 2
    assert db_session.scalar(select(func.count()).select_from(Opportunity)) == 7
    assert db_session.scalar(select(func.count()).select_from(OpportunityOrigin)) == 9
    assert db_session.scalar(select(func.count()).select_from(CampaignPostingLink)) == 0

    campaigns = db_session.scalars(
        select(Opportunity).where(Opportunity.kind == OpportunityKind.CAMPAIGN.value)
    ).all()
    assert len(campaigns) == 2
    assert {campaign.display_title for campaign in campaigns} == {
        "AI产品经理、数据科学家、大模型应用工程师",
        "售前解决方案工程师、具身控制算法工程师、嵌入式工程师",
    }

    pm1001 = db_session.scalar(
        select(Opportunity).where(Opportunity.official_job_id == "PM1001")
    )
    pm1002 = db_session.scalar(
        select(Opportunity).where(Opportunity.official_job_id == "PM1002")
    )
    assert pm1001 is not None
    assert pm1002 is not None
    assert pm1001.id != pm1002.id
    assert len(pm1001.origins) == 2

    claim_names = {
        claim.field_name
        for claim in db_session.scalars(
            select(FieldClaim).where(FieldClaim.opportunity_id == pm1001.id)
        )
    }
    assert {
        "company",
        "title",
        "cities",
        "graduation_years",
        "recruitment_type",
        "employer_type",
        "written_test",
        "deadline",
        "status",
        "announcement_url",
        "apply_url",
    } <= claim_names

    serialized = opportunity_list_item(db_session, pm1001)
    assert serialized.employer_type == "民营企业"
    assert serialized.written_test == "免笔试"

    deadline_claims = db_session.scalars(
        select(FieldClaim).where(
            FieldClaim.opportunity_id == pm1001.id,
            FieldClaim.field_name == "deadline",
        )
    ).all()
    assert {json.loads(claim.raw_value) for claim in deadline_claims} == {
        "2026-09-30",
        "2026-10-10",
    }
    assert not any(claim.selected for claim in deadline_claims)
    assert all(claim.observed_at is not None for claim in deadline_claims)
    assert all(claim.evidence_label and claim.parser_version for claim in deadline_claims)

    linked_raw_ids = set(db_session.scalars(select(OpportunityOrigin.raw_record_id)))
    raw_ids = set(db_session.scalars(select(RawRecord.id)))
    assert linked_raw_ids == raw_ids


def test_materialization_is_idempotent_for_the_same_raw_batch(db_session: Session) -> None:
    batch_id = _import_demo(
        db_session,
        "source_alpha.csv",
        source_id="alpha",
        source_name="供应商甲",
    )
    materialize_batch(db_session, batch_id)
    opportunity_count = db_session.scalar(select(func.count()).select_from(Opportunity))
    claim_count = db_session.scalar(select(func.count()).select_from(FieldClaim))

    repeated = materialize_batch(db_session, batch_id)

    assert repeated.created_opportunities == 0
    assert repeated.reused_opportunities == 0
    assert repeated.skipped_records == 5
    assert repeated.created_claims == 0
    assert db_session.scalar(select(func.count()).select_from(Opportunity)) == opportunity_count
    assert db_session.scalar(select(func.count()).select_from(FieldClaim)) == claim_count


def test_compound_hint_creates_review_candidate_instead_of_merging(
    db_session: Session,
    tmp_path: Path,
) -> None:
    header = "公司名称,招聘岗位,工作城市,毕业年份,招聘批次,截止时间\n"
    first_row = "深蓝数据,数据产品经理,上海,2027届,秋招,2026-09-01\n"
    second_row = "深蓝数据,数据产品经理,上海,2027届,秋招,2026-09-15\n"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    first_path.write_text(header + first_row, encoding="utf-8")
    # 两个独立来源的截止时间不同；身份字段仍构成相同的复合 hint。
    second_path.write_text(header + second_row, encoding="utf-8")

    batch_ids = []
    for path, source_id in ((first_path, "first"), (second_path, "second")):
        snapshot = parse_snapshot(
            path,
            source_name=source_id,
            source_kind=SourceKind.SYNTHETIC,
        )
        imported = import_parsed_snapshot(
            db_session,
            snapshot,
            source_id=source_id,
            independence_group=source_id,
        )
        batch_ids.append(imported.batch_id)
    materialize_batch(db_session, batch_ids[0])
    materialize_batch(db_session, batch_ids[1])

    assert db_session.scalar(select(func.count()).select_from(Opportunity)) == 2
    candidate = db_session.scalar(select(DuplicateCandidate))
    assert candidate is not None
    assert candidate.decision == DuplicateDecision.REVIEW.value
    assert "复合 hint" in candidate.decision_reason


def test_same_official_url_without_job_id_reuses_opportunity(
    db_session: Session,
    tmp_path: Path,
) -> None:
    header = "公司名称,招聘岗位,工作城市,毕业年份,招聘批次,截止时间,投递链接\n"
    row_template = (
        "深蓝数据,数据产品经理,上海,2027届,秋招,"
        "{deadline},https://careers.deepblue.example/openings/product-manager\n"
    )
    batch_ids = []
    for source_id in ("first", "second"):
        path = tmp_path / f"{source_id}.csv"
        source_row = row_template.format(
            deadline="2026-09-01" if source_id == "first" else "2026-09-15"
        )
        path.write_text(header + source_row, encoding="utf-8")
        snapshot = parse_snapshot(
            path,
            source_name=source_id,
            source_kind=SourceKind.SYNTHETIC,
        )
        imported = import_parsed_snapshot(
            db_session,
            snapshot,
            source_id=source_id,
            independence_group=source_id,
        )
        batch_ids.append(imported.batch_id)
    materialize_batch(db_session, batch_ids[0])
    materialize_batch(db_session, batch_ids[1])

    opportunity = db_session.scalar(select(Opportunity))
    assert opportunity is not None
    assert db_session.scalar(select(func.count()).select_from(Opportunity)) == 1
    assert len(opportunity.origins) == 2


def test_different_official_job_ids_are_explicitly_separate(
    db_session: Session,
    tmp_path: Path,
) -> None:
    header = "公司名称,招聘岗位,工作城市,毕业年份,招聘批次,投递链接\n"
    batch_ids = []
    for source_id, job_id in (("first", "ABCD1001"), ("second", "WXYZ1002")):
        path = tmp_path / f"{source_id}.csv"
        path.write_text(
            header
            + f"深蓝数据,数据产品经理,上海,2027届,秋招,https://careers.deepblue.example/jobs/{job_id}\n",
            encoding="utf-8",
        )
        snapshot = parse_snapshot(
            path,
            source_name=source_id,
            source_kind=SourceKind.SYNTHETIC,
        )
        imported = import_parsed_snapshot(
            db_session,
            snapshot,
            source_id=source_id,
            independence_group=source_id,
        )
        batch_ids.append(imported.batch_id)
    materialize_batch(db_session, batch_ids[0])
    materialize_batch(db_session, batch_ids[1])

    assert db_session.scalar(select(func.count()).select_from(Opportunity)) == 2
    job_ids = set(db_session.scalars(select(Opportunity.official_job_id)))
    assert job_ids == {"ABCD1001", "WXYZ1002"}


def test_official_source_claim_wins_without_deleting_aggregator_claim(
    db_session: Session,
    tmp_path: Path,
) -> None:
    header = "公司名称,招聘岗位,工作城市,毕业年份,招聘批次,截止日期,投递链接\n"
    batch_ids = []
    sources = (
        ("aggregator", SourceKind.SYNTHETIC, "2026-09-30"),
        ("official", SourceKind.OFFICIAL, "2026-10-15"),
    )
    for source_id, source_kind, deadline in sources:
        path = tmp_path / f"{source_id}.csv"
        path.write_text(
            header
            + f"深蓝数据,数据产品经理,上海,2027届,秋招,{deadline},https://careers.deepblue.example/jobs/DP2027\n",
            encoding="utf-8",
        )
        snapshot = parse_snapshot(
            path,
            source_name=source_id,
            source_kind=source_kind,
        )
        imported = import_parsed_snapshot(
            db_session,
            snapshot,
            source_id=source_id,
            independence_group=source_id,
        )
        batch_ids.append(imported.batch_id)
    materialize_batch(db_session, batch_ids[0])
    first_opportunity = db_session.scalar(select(Opportunity))
    assert first_opportunity is not None
    first_opportunity.organization.official_domain = "careers.deepblue.example"
    first_opportunity.organization.official_domain_verified = True
    first_opportunity.organization.official_domain_source = "test-user-confirmation"
    db_session.commit()
    materialize_batch(db_session, batch_ids[1])

    opportunity = db_session.scalar(select(Opportunity))
    assert opportunity is not None
    deadline_claims = db_session.scalars(
        select(FieldClaim).where(
            FieldClaim.opportunity_id == opportunity.id,
            FieldClaim.field_name == "deadline",
        )
    ).all()
    assert len(deadline_claims) == 2
    selected = [claim for claim in deadline_claims if claim.selected]
    assert len(selected) == 1
    assert json.loads(selected[0].raw_value) == "2026-10-15"
    assert selected[0].authority > min(claim.authority for claim in deadline_claims)
    assert {json.loads(claim.raw_value) for claim in deadline_claims} == {
        "2026-09-30",
        "2026-10-15",
    }


def test_paid_table_domain_is_only_a_candidate_trust_anchor(
    db_session: Session,
    tmp_path: Path,
) -> None:
    path = tmp_path / "paid.csv"
    path.write_text(
        "公司名称,招聘岗位,工作城市,毕业年份,投递链接\n"
        "未核验公司,AI产品经理,上海,2027届,https://evil.example:443/jobs/E1\n",
        encoding="utf-8",
    )
    snapshot = parse_snapshot(
        path,
        source_name="付费聚合表",
        source_kind=SourceKind.PAID_TABLE,
    )
    imported = import_parsed_snapshot(
        db_session,
        snapshot,
        source_id="paid-untrusted",
        independence_group="paid-vendor",
    )
    materialize_batch(db_session, imported.batch_id)
    opportunity = db_session.scalar(select(Opportunity))
    assert opportunity is not None
    assert opportunity.organization is not None
    assert opportunity.organization.candidate_domain == "evil.example"
    assert opportunity.organization.official_domain == ""
    assert opportunity.organization.official_domain_verified is False


def test_invalid_official_source_host_still_fails_closed(
    db_session: Session,
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid-official.csv"
    path.write_text(
        "公司名称,招聘岗位,工作城市,投递链接\n"
        "伪官方源,AI产品经理,上海,https://com/jobs/ABCD1234\n",
        encoding="utf-8",
    )
    snapshot = parse_snapshot(
        path,
        source_name="用户声称官方源",
        source_kind=SourceKind.OFFICIAL,
    )
    imported = import_parsed_snapshot(
        db_session,
        snapshot,
        source_id="invalid-official",
        independence_group="invalid-official",
    )
    materialize_batch(db_session, imported.batch_id)
    opportunity = db_session.scalar(select(Opportunity))
    assert opportunity is not None
    assert opportunity.organization is not None
    assert opportunity.organization.candidate_domain == "com"
    assert opportunity.organization.official_domain == ""
    assert opportunity.organization.official_domain_verified is False


def test_explicit_official_job_id_is_exact_even_when_titles_differ(
    db_session: Session,
    tmp_path: Path,
) -> None:
    header = "公司名称,招聘岗位,工作城市,毕业年份,招聘批次,岗位ID\n"
    batch_ids = []
    for source_id, title in (("first", "AI产品经理"), ("second", "大模型产品经理")):
        path = tmp_path / f"{source_id}.csv"
        path.write_text(
            header + f"深蓝数据,{title},上海,2027届,秋招,DP-2027-001\n",
            encoding="utf-8",
        )
        snapshot = parse_snapshot(
            path,
            source_name=source_id,
            source_kind=SourceKind.SYNTHETIC,
        )
        imported = import_parsed_snapshot(
            db_session,
            snapshot,
            source_id=source_id,
            independence_group=source_id,
        )
        batch_ids.append(imported.batch_id)
    materialize_batch(db_session, batch_ids[0])
    materialize_batch(db_session, batch_ids[1])

    opportunity = db_session.scalar(select(Opportunity))
    assert opportunity is not None
    assert db_session.scalar(select(func.count()).select_from(Opportunity)) == 1
    assert opportunity.official_job_id == "DP-2027-001"
    assert len(opportunity.origins) == 2


def test_latest_stable_source_record_title_is_displayed_and_searchable(
    db_session: Session,
    tmp_path: Path,
) -> None:
    header = "记录ID,公司名称,招聘岗位,工作城市,毕业年份,招聘批次\n"
    batches: list[str] = []
    for index, title in enumerate(("AI产品实习生", "AI产品经理实习生"), start=1):
        path = tmp_path / f"title-{index}.csv"
        path.write_text(
            header + f"R-1,深蓝数据,{title},上海,2027届,秋招\n",
            encoding="utf-8",
        )
        snapshot = parse_snapshot(
            path,
            source_name="稳定供应商",
            source_kind=SourceKind.SYNTHETIC,
        )
        imported = import_parsed_snapshot(
            db_session,
            snapshot,
            source_id="stable-vendor",
            independence_group="stable-vendor",
        )
        batches.append(imported.batch_id)
    for batch_id in batches:
        materialize_batch(db_session, batch_id)

    opportunity = db_session.scalar(select(Opportunity))
    assert opportunity is not None
    assert db_session.scalar(select(func.count()).select_from(Opportunity)) == 1
    item = opportunity_list_item(db_session, opportunity)
    assert item.title == "AI产品经理实习生"
    selected_title = db_session.scalar(
        select(FieldClaim).where(
            FieldClaim.opportunity_id == opportunity.id,
            FieldClaim.field_name == "title",
            FieldClaim.selected.is_(True),
        )
    )
    assert selected_title is not None
    assert json.loads(selected_title.raw_value) == "AI产品经理实习生"


def test_stable_source_record_id_never_reuses_across_companies(
    db_session: Session,
    tmp_path: Path,
) -> None:
    header = "记录ID,公司名称,招聘岗位,工作城市,毕业年份,招聘批次\n"
    batches: list[str] = []
    for index, company in enumerate(("甲公司", "乙公司"), start=1):
        path = tmp_path / f"company-{index}.csv"
        path.write_text(
            header + f"R-1,{company},AI产品经理,上海,2027届,秋招\n",
            encoding="utf-8",
        )
        snapshot = parse_snapshot(
            path,
            source_name="稳定供应商",
            source_kind=SourceKind.SYNTHETIC,
        )
        imported = import_parsed_snapshot(
            db_session,
            snapshot,
            source_id="stable-vendor",
            independence_group="stable-vendor",
        )
        batches.append(imported.batch_id)
    for batch_id in batches:
        materialize_batch(db_session, batch_id)

    opportunities = list(db_session.scalars(select(Opportunity)))
    assert len(opportunities) == 2
    assert {item.organization.canonical_name for item in opportunities} == {
        "甲公司",
        "乙公司",
    }
    assert all(len(item.origins) == 1 for item in opportunities)
