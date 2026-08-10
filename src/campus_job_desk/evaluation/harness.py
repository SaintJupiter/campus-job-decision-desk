from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, distinct, func, select
from sqlalchemy.orm import Session, sessionmaker

from campus_job_desk.api.routes.opportunities import router as opportunities_router
from campus_job_desk.api.routes.workspace import router as workspace_router
from campus_job_desk.database import create_database_engine, create_schema, get_session
from campus_job_desk.domain.classify import classify_record, official_job_id_matches_url
from campus_job_desk.domain.decisions import JobDecisionContext
from campus_job_desk.domain.enums import OpportunityKind, VerificationResult
from campus_job_desk.domain.profile import JobPreferences
from campus_job_desk.domain.schemas import CanonicalRecord
from campus_job_desk.models import (
    DataSource,
    DecisionSnapshot,
    DuplicateCandidate,
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
from campus_job_desk.services.dedup import assess_duplicate_pair
from campus_job_desk.services.profile import ProfileService
from campus_job_desk.services.verification import (
    VerificationValidationError,
    normalize_official_domain,
    normalize_official_scope,
    record_verification,
)

HARNESS_VERSION = "evaluation-harness.v1"
DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "evaluation" / "fixtures" / "gold.json"
NO_OUTCOME_CLAIM = (
    "This harness does not measure users, interviews, applications, hiring outcomes, "
    "or production accuracy."
)


class EvaluationHarness:
    """Run deterministic fixtures plus aggregate-only database and API checks.

    The fixture manifest is fully synthetic. Database inspection deliberately emits
    counts and ratios only: it never serializes job titles, company names, URLs,
    resume facts, raw rows, or claim values.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        database_label: str = "local-baseline",
        fixture_path: Path = DEFAULT_FIXTURE_PATH,
        owns_engine: bool = False,
        temporary_directory: Any = None,
    ) -> None:
        self.engine = engine
        self.database_label = database_label
        self.fixture_path = fixture_path.resolve()
        self.owns_engine = owns_engine
        self.temporary_directory = temporary_directory

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
        *,
        database_label: str = "local-baseline",
        fixture_path: Path = DEFAULT_FIXTURE_PATH,
    ) -> "EvaluationHarness":
        if database_url.startswith("sqlite:///") and not database_url.endswith(":memory:"):
            source_path = Path(database_url.removeprefix("sqlite:///")).expanduser().resolve()
            if not source_path.is_file():
                raise FileNotFoundError(f"evaluation database does not exist: {source_path}")
            temporary_directory = tempfile.TemporaryDirectory(prefix="campus-job-desk-evaluation-")
            snapshot_path = Path(temporary_directory.name) / "baseline.sqlite"
            try:
                source = sqlite3.connect(
                    f"file:{source_path}?mode=ro",
                    uri=True,
                    check_same_thread=False,
                )
                destination = sqlite3.connect(snapshot_path)
                try:
                    source.backup(destination)
                finally:
                    destination.close()
                    source.close()
                snapshot_engine = create_database_engine(f"sqlite:///{snapshot_path}")
                create_schema(snapshot_engine)
            except Exception:
                temporary_directory.cleanup()
                raise
            return cls(
                snapshot_engine,
                database_label=database_label,
                fixture_path=fixture_path,
                owns_engine=True,
                temporary_directory=temporary_directory,
            )
        return cls(
            create_database_engine(database_url),
            database_label=database_label,
            fixture_path=fixture_path,
            owns_engine=True,
        )

    def close(self) -> None:
        if self.owns_engine:
            self.engine.dispose()
        if self.temporary_directory is not None:
            self.temporary_directory.cleanup()

    def run(
        self,
        *,
        performance_samples: int = 5,
        performance_warmups: int = 1,
        generated_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        if performance_samples < 1:
            raise ValueError("performance_samples must be at least 1")
        if performance_warmups < 0:
            raise ValueError("performance_warmups cannot be negative")
        manifest_bytes = self.fixture_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        fixture_results = self.evaluate_fixtures(manifest)
        generated = generated_at or datetime.now(timezone.utc)
        return {
            "schema_version": "campus-job-desk-evaluation-report.v1",
            "harness_version": HARNESS_VERSION,
            "generated_at": _canonical_datetime(generated),
            "methodology": {
                "fixture_manifest": self.fixture_path.name,
                "fixture_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "fixture_data_class": manifest["provenance"]["data_class"],
                "contract_definition": (
                    "Declared invariants and safety boundaries; every case must pass."
                ),
                "heuristic_sample_definition": (
                    "Small developer-authored synthetic examples used for regression, "
                    "not a representative benchmark."
                ),
                "database_policy": (
                    "Aggregate counts and ratios only; no source row, posting text, "
                    "company, URL, resume evidence, or claim value is emitted."
                ),
                "database_snapshot_policy": (
                    "SQLite inputs are copied with the SQLite backup API and migrations "
                    "run only on the disposable copy; the source database is not modified."
                ),
                "outcome_claim_policy": NO_OUTCOME_CLAIM,
            },
            "fixture_summary": _fixture_summary(fixture_results),
            "fixture_results": fixture_results,
            "database_quality": self.database_quality(),
            "api_performance": self.api_performance(
                samples=performance_samples,
                warmups=performance_warmups,
            ),
            "limitations": list(manifest["provenance"]["limitations"])
            + [
                "API timings are local-process observations, not production SLOs.",
                "Database quality reports structural completeness, not semantic correctness of every row.",
            ],
        }

    def evaluate_fixtures(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for suite_key, suite_label in (
            ("contract_boundary", "contract_boundary"),
            ("heuristic_samples", "heuristic_sample"),
        ):
            suite = manifest[suite_key]
            results.extend(
                self._classification_results(suite.get("classification", []), suite=suite_label)
            )
            results.extend(self._dedup_results(suite.get("deduplication", []), suite=suite_label))
            results.extend(
                self._decision_results(suite.get("decision_guardrails", []), suite=suite_label)
            )
            results.extend(
                self._verification_results(
                    suite.get("verification_guardrails", []), suite=suite_label
                )
            )
        return results

    def database_quality(self) -> dict[str, Any]:
        with Session(self.engine) as session:
            table_counts = {
                "sources": _count(session, DataSource),
                "import_batches": _count(session, ImportBatch),
                "raw_records": _count(session, RawRecord),
                "organizations": _count(session, Organization),
                "opportunities": _count(session, Opportunity),
                "opportunity_origins": _count(session, OpportunityOrigin),
                "field_claims": _count(session, FieldClaim),
                "duplicate_candidates": _count(session, DuplicateCandidate),
                "verification_attempts": _count(session, VerificationAttempt),
                "decision_snapshots": _count(session, DecisionSnapshot),
                "profile_facts": _count(session, ProfileFact),
                "preferences": _count(session, UserPreference),
                "shortlist_entries": _count(session, ShortlistEntry),
            }
            raw_with_origin = int(
                session.scalar(select(func.count(distinct(OpportunityOrigin.raw_record_id)))) or 0
            )
            opportunities_with_origin = int(
                session.scalar(select(func.count(distinct(OpportunityOrigin.opportunity_id)))) or 0
            )
            duplicate_selected_groups = int(
                session.scalar(
                    select(func.count()).select_from(
                        select(FieldClaim.opportunity_id, FieldClaim.field_name)
                        .where(FieldClaim.selected.is_(True), FieldClaim.active.is_(True))
                        .group_by(FieldClaim.opportunity_id, FieldClaim.field_name)
                        .having(func.count(FieldClaim.id) > 1)
                        .subquery()
                    )
                )
                or 0
            )
            duplicate_current_decisions = int(
                session.scalar(
                    select(func.count()).select_from(
                        select(DecisionSnapshot.opportunity_id)
                        .where(DecisionSnapshot.is_current.is_(True))
                        .group_by(DecisionSnapshot.opportunity_id)
                        .having(func.count(DecisionSnapshot.id) > 1)
                        .subquery()
                    )
                )
                or 0
            )
            verified_domains = int(
                session.scalar(
                    select(func.count(Organization.id)).where(
                        Organization.official_domain_verified.is_(True)
                    )
                )
                or 0
            )
            applicable_verifications = int(
                session.scalar(
                    select(func.count(VerificationAttempt.id))
                    .join(
                        Opportunity,
                        Opportunity.id == VerificationAttempt.opportunity_id,
                    )
                    .join(Organization, Organization.id == Opportunity.organization_id)
                    .where(
                        Organization.official_domain_verified.is_(True),
                        VerificationAttempt.evidence_scope == Opportunity.kind,
                        VerificationAttempt.verified_domain == Organization.official_domain,
                        VerificationAttempt.verified_scope_path
                        == Organization.official_scope_path,
                    )
                )
                or 0
            )
            raw_count = table_counts["raw_records"]
            opportunity_count = table_counts["opportunities"]
            checks = {
                "raw_records_with_origin": raw_with_origin,
                "raw_records_without_origin": max(raw_count - raw_with_origin, 0),
                "raw_materialization_coverage": _ratio(raw_with_origin, raw_count),
                "opportunities_with_origin": opportunities_with_origin,
                "opportunities_without_origin": max(
                    opportunity_count - opportunities_with_origin, 0
                ),
                "opportunity_origin_coverage": _ratio(opportunities_with_origin, opportunity_count),
                "active_selected_claim_duplicate_groups": duplicate_selected_groups,
                "current_decision_duplicate_groups": duplicate_current_decisions,
                "verified_official_domains": verified_domains,
                "scope_and_domain_applicable_verifications": applicable_verifications,
            }
            return {
                "database_label": self.database_label,
                "privacy_mode": "aggregate_only",
                "table_counts": table_counts,
                "distributions": {
                    "raw_parse_status": _group_counts(session, RawRecord.parse_status),
                    "raw_kind_prediction": _group_counts(session, RawRecord.kind_prediction),
                    "opportunity_kind": _group_counts(session, Opportunity.kind),
                    "opportunity_review_status": _group_counts(session, Opportunity.review_status),
                    "duplicate_decision": _group_counts(session, DuplicateCandidate.decision),
                    "verification_result": _group_counts(session, VerificationAttempt.result),
                    "current_decision_eligibility": _group_counts(
                        session,
                        DecisionSnapshot.eligibility,
                        DecisionSnapshot.is_current.is_(True),
                    ),
                    "current_decision_evidence_fit": _group_counts(
                        session,
                        DecisionSnapshot.evidence_fit,
                        DecisionSnapshot.is_current.is_(True),
                    ),
                    "current_decision_trust": _group_counts(
                        session,
                        DecisionSnapshot.trust,
                        DecisionSnapshot.is_current.is_(True),
                    ),
                },
                "structural_checks": checks,
            }

    def api_performance(self, *, samples: int, warmups: int) -> dict[str, Any]:
        factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )

        def evaluation_session():  # type: ignore[no-untyped-def]
            with factory() as session:
                yield session

        benchmark_app = FastAPI()
        benchmark_app.include_router(opportunities_router)
        benchmark_app.include_router(workspace_router)
        benchmark_app.dependency_overrides[get_session] = evaluation_session
        with Session(self.engine) as session:
            detail_id = session.scalar(
                select(Opportunity.id)
                .where(Opportunity.review_status != "MERGED")
                .order_by(Opportunity.id)
                .limit(1)
            )
        endpoints: list[tuple[str, Optional[str]]] = [
            (
                "opportunity_list_first_page",
                "/api/opportunities?page=1&page_size=30&kind=POSTING",
            ),
            ("workspace_dashboard", "/api/workspace/dashboard"),
            (
                "opportunity_detail",
                f"/api/opportunities/{detail_id}" if detail_id else None,
            ),
        ]
        endpoint_results: list[dict[str, Any]] = []
        with TestClient(benchmark_app) as client:
            for label, path in endpoints:
                if path is None:
                    endpoint_results.append(
                        {
                            "endpoint": label,
                            "status": "skipped_empty_database",
                            "sample_count": 0,
                        }
                    )
                    continue
                for _ in range(warmups):
                    client.get(path)
                timings: list[float] = []
                statuses: list[int] = []
                response_bytes: list[int] = []
                for _ in range(samples):
                    started = perf_counter()
                    response = client.get(path)
                    timings.append((perf_counter() - started) * 1000)
                    statuses.append(response.status_code)
                    response_bytes.append(len(response.content))
                endpoint_results.append(
                    {
                        "endpoint": label,
                        "status": "measured",
                        "sample_count": samples,
                        "warmup_count": warmups,
                        "http_statuses": sorted(set(statuses)),
                        "latency_ms": {
                            "min": round(min(timings), 2),
                            "median": round(statistics.median(timings), 2),
                            "p95": round(_percentile(timings, 0.95), 2),
                            "max": round(max(timings), 2),
                        },
                        "response_bytes": {
                            "min": min(response_bytes),
                            "max": max(response_bytes),
                        },
                    }
                )
        return {
            "measurement_scope": "local in-process FastAPI TestClient over selected database",
            "is_production_slo": False,
            "endpoints": endpoint_results,
        }

    @staticmethod
    def _classification_results(
        fixtures: Iterable[dict[str, Any]], *, suite: str
    ) -> list[dict[str, Any]]:
        results = []
        for fixture in fixtures:
            expected = fixture["expected_kind"]
            actual = classify_record(CanonicalRecord(**fixture["record"])).kind.value
            results.append(
                _case_result(
                    fixture["id"], suite, "campaign_posting_classification", expected, actual
                )
            )
        return results

    @staticmethod
    def _dedup_results(fixtures: Iterable[dict[str, Any]], *, suite: str) -> list[dict[str, Any]]:
        results = []
        for fixture in fixtures:
            other_data = fixture["other"]
            other = Opportunity(
                id=f"fixture-other-{fixture['id']}",
                organization_id="fixture-org",
                kind=OpportunityKind.POSTING.value,
                display_title=other_data["title"],
                official_job_id=other_data.get("official_job_id"),
            )
            values = {
                name: json.dumps(other_data.get(name, fallback), ensure_ascii=False)
                for name, fallback in (
                    ("title", other_data["title"]),
                    ("cities", []),
                    ("graduation_years", []),
                    ("recruitment_type", ""),
                )
            }
            assessment = assess_duplicate_pair(
                CanonicalRecord(**fixture["current"]),
                other,
                values,
                same_compound_hint=fixture["same_compound_hint"],
            )
            actual = assessment.decision.value
            result = _case_result(
                fixture["id"],
                suite,
                "duplicate_candidate_decision",
                fixture["expected_decision"],
                actual,
            )
            result["diagnostics"] = {
                "score": round(assessment.score, 4),
                "same_compound_hint": bool(assessment.features["same_compound_hint"]),
                "official_id_conflict": bool(
                    fixture["current"].get("official_job_id")
                    and other_data.get("official_job_id")
                    and fixture["current"].get("official_job_id")
                    != other_data.get("official_job_id")
                ),
            }
            results.append(result)
        return results

    @staticmethod
    def _decision_results(
        fixtures: Iterable[dict[str, Any]], *, suite: str
    ) -> list[dict[str, Any]]:
        results = []
        profile_service = ProfileService()
        decision_service = DecisionService()
        for fixture in fixtures:
            profile_data = fixture["profile"]
            profile = profile_service.extract_text(
                profile_data["resume_text"],
                source_name="synthetic-evaluation-resume.txt",
                preferences=JobPreferences(
                    accepted_cities=profile_data.get("accepted_cities", []),
                    accepted_recruitment_types=profile_data.get("accepted_recruitment_types", []),
                ),
            )
            if profile_data.get("confirm_all", False):
                profile = profile_service.confirm_facts(
                    profile, {fact.fact_id for fact in profile.facts}
                )
            context = JobDecisionContext(**fixture["context"])
            bundle = decision_service.evaluate(
                context,
                profile,
                as_of=datetime.fromisoformat(fixture["as_of"]),
            )
            actual_all = {
                "eligibility": bundle.eligibility.result.value,
                "evidence_fit": bundle.evidence_fit.result.value,
                "trust": bundle.trust.result.value,
            }
            expected = fixture["expected"]
            actual = {axis: actual_all[axis] for axis in expected}
            results.append(
                _case_result(
                    fixture["id"], suite, "three_axis_decision_guardrail", expected, actual
                )
            )
        return results

    @staticmethod
    def _verification_results(
        fixtures: Iterable[dict[str, Any]], *, suite: str
    ) -> list[dict[str, Any]]:
        results = []
        for fixture in fixtures:
            expected: Any
            operation = fixture.get("operation", "normalize_domain")
            if operation == "normalize_domain":
                try:
                    actual: Any = normalize_official_domain(fixture["candidate"])
                except VerificationValidationError as exc:
                    actual = {"error": str(exc)}
            elif operation == "normalize_scope":
                try:
                    domain, scope_path = normalize_official_scope(fixture["candidate"])
                    actual = {"domain": domain, "scope_path": scope_path}
                except VerificationValidationError as exc:
                    actual = {"error": str(exc)}
            elif operation == "official_job_id_match":
                actual = official_job_id_matches_url(
                    fixture["candidate"], fixture["official_job_id"]
                )
            elif operation == "record_verification":
                actual = _evaluate_isolated_verification(fixture)
            else:
                actual = {"error": f"unsupported fixture operation: {operation}"}
            if "expected_error" in fixture:
                expected = {"error": fixture["expected_error"]}
            else:
                expected = fixture["expected"]
            results.append(
                _case_result(fixture["id"], suite, "official_domain_guardrail", expected, actual)
            )
        return results


def write_report(report: dict[str, Any], *, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    fixture_summary = report["fixture_summary"]
    database = report["database_quality"]
    lines = [
        "# 校招岗位决策台可复现评测",
        "",
        f"- 生成时间：`{report['generated_at']}`",
        f"- 评测器：`{report['harness_version']}`",
        f"- 数据库标识：`{database['database_label']}`",
        "- 数据库输出策略：仅聚合计数与比率，不输出任何岗位、公司、链接、简历或来源原文。",
        "",
        "> 边界声明：全部 gold fixtures 都由开发者合成。经验性样本只是小型回归集，"
        "不是真实用户、企业、投递或面试数据，不支持任何录用率或线上准确率声称。",
        "",
        "## 结论摘要",
        "",
        f"- Contract/boundary：**{fixture_summary['contract_boundary']['passed']} / "
        f"{fixture_summary['contract_boundary']['total']}** 通过。",
        f"- Heuristic sample：**{fixture_summary['heuristic_sample']['passed']} / "
        f"{fixture_summary['heuristic_sample']['total']}** 与人工标注一致；只代表本合成样本集。",
        f"- 私有基线结构：{database['table_counts']['raw_records']} 条原始记录，"
        f"{database['table_counts']['opportunities']} 个机会实体，"
        f"{database['table_counts']['field_claims']} 条字段 claim。",
        "",
        "## Gold fixture 结果",
        "",
        "| 样本 | 集合 | 能力 | 期望 | 实际 | 结果 |",
        "|---|---|---|---|---|---|",
    ]
    for item in report["fixture_results"]:
        lines.append(
            "| `{id}` | {suite} | {component} | `{expected}` | `{actual}` | {status} |".format(
                id=item["id"],
                suite=item["suite"],
                component=item["component"],
                expected=_compact_json(item["expected"]),
                actual=_compact_json(item["actual"]),
                status="通过" if item["passed"] else "失败",
            )
        )
    lines.extend(
        [
            "",
            "Contract 样本用于防止边界回归，必须 100% 通过。Heuristic sample 的比率不可外推。",
            "输入、期望与来源声明可在 `evaluation/fixtures/gold.json` 逐条审阅。",
            "",
            "## 数据库数据质量概况",
            "",
            "### 表计数",
            "",
            "| 对象 | 数量 |",
            "|---|---:|",
        ]
    )
    for name, count in database["table_counts"].items():
        lines.append(f"| `{name}` | {count} |")
    lines.extend(
        [
            "",
            "### 结构完整性",
            "",
            "| 检查 | 结果 |",
            "|---|---:|",
        ]
    )
    for name, value in database["structural_checks"].items():
        lines.append(f"| `{name}` | {value} |")
    lines.extend(["", "### 分布", ""])
    for name, values in database["distributions"].items():
        lines.append(f"- `{name}`：`{_compact_json(values)}`")
    lines.extend(
        [
            "",
            "## API 本地性能观测",
            "",
            "此数据是同进程 FastAPI TestClient 在指定本地数据库上的观测，不是生产 SLO。",
            "",
            "| 端点 | 样本 | HTTP | min ms | median ms | p95 ms | max ms |",
            "|---|---:|---|---:|---:|---:|---:|",
        ]
    )
    for item in report["api_performance"]["endpoints"]:
        latency = item.get("latency_ms", {})
        lines.append(
            f"| `{item['endpoint']}` | {item['sample_count']} | "
            f"{_compact_json(item.get('http_statuses', item['status']))} | "
            f"{latency.get('min', '-')} | {latency.get('median', '-')} | "
            f"{latency.get('p95', '-')} | {latency.get('max', '-')} |"
        )
    lines.extend(["", "## 局限", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def _fixture_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for suite in ("contract_boundary", "heuristic_sample"):
        selected = [result for result in results if result["suite"] == suite]
        passed = sum(result["passed"] for result in selected)
        summary[suite] = {
            "total": len(selected),
            "passed": passed,
            "failed": len(selected) - passed,
            "exact_match_rate_on_fixture_set": _ratio(passed, len(selected)),
        }
    return summary


def _case_result(
    case_id: str, suite: str, component: str, expected: Any, actual: Any
) -> dict[str, Any]:
    return {
        "id": case_id,
        "suite": suite,
        "component": component,
        "expected": expected,
        "actual": actual,
        "passed": actual == expected,
    }


def _count(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _evaluate_isolated_verification(fixture: dict[str, Any]) -> Any:
    """Exercise the mutating verification service only on a disposable database."""

    engine = create_database_engine("sqlite:///:memory:")
    create_schema(engine)
    try:
        with Session(engine) as session:
            organization = Organization(
                canonical_name="合成评测公司",
                normalized_name="合成评测公司",
                official_domain=fixture.get(
                    "official_domain", "jobs.synthetic-example.com"
                ),
                official_scope_path=fixture.get("official_scope_path", ""),
                official_domain_verified=True,
                official_domain_source="synthetic-evaluation-fixture",
            )
            session.add(organization)
            session.flush()
            opportunity = Opportunity(
                organization_id=organization.id,
                kind=OpportunityKind.POSTING.value,
                display_title="合成评测岗位",
                official_job_id="PM-1001",
                review_status="READY",
            )
            session.add(opportunity)
            session.flush()
            try:
                record_verification(
                    session,
                    opportunity_id=opportunity.id,
                    result=VerificationResult(fixture["result"]),
                    url=fixture["candidate"],
                    evidence_excerpt=fixture.get("evidence_excerpt", ""),
                    extracted_fields=fixture.get("extracted_fields", {}),
                    reviewer="synthetic-evaluation",
                )
            except VerificationValidationError as exc:
                return {"error": str(exc)}
            return "accepted"
    finally:
        engine.dispose()


def _group_counts(session: Session, column: Any, *filters: Any) -> dict[str, int]:
    rows = session.execute(
        select(column, func.count()).where(*filters).group_by(column).order_by(column)
    )
    return {str(value): int(count) for value, count in rows}


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _canonical_datetime(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _compact_json(value: Any) -> str:
    if isinstance(value, str):
        return value.replace("|", "\\|")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace(
        "|", "\\|"
    )
