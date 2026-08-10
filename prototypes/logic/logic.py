from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from enum import Enum, IntEnum
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


class OpportunityKind(str, Enum):
    CAMPAIGN = "CAMPAIGN"
    POSTING = "POSTING"


class Authority(IntEnum):
    AGGREGATOR = 10
    OFFICIAL_CAMPAIGN = 20
    OFFICIAL_POSTING = 30


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
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class Trust(str, Enum):
    VERIFIED = "VERIFIED"
    VERIFIED_WITH_CONFLICT = "VERIFIED_WITH_CONFLICT"
    CONSISTENT = "CONSISTENT"
    CONFLICTED = "CONFLICTED"
    UNCONFIRMED = "UNCONFIRMED"


@dataclass(frozen=True)
class RawRecord:
    source: str
    company: str
    title: str
    cities: tuple[str, ...]
    graduation_years: tuple[str, ...]
    education: tuple[str, ...]
    recruitment_type: str
    url: str
    official_job_id: str | None = None
    source_authority: Authority = Authority.AGGREGATOR


@dataclass(frozen=True)
class Claim:
    field_name: str
    value: Any
    source: str
    authority: Authority
    observed_at: str
    evidence: str


@dataclass(frozen=True)
class Verification:
    result: VerificationResult
    checked_at: str
    url: str
    claims: tuple[Claim, ...] = ()
    evidence: str = ""


@dataclass(frozen=True)
class Profile:
    graduation_year: str = "2027届"
    education: str = "硕士"
    preferred_cities: tuple[str, ...] = ("上海",)
    target_keywords: tuple[str, ...] = ("AI", "产品", "数据", "解决方案", "平台")


@dataclass(frozen=True)
class Scenario:
    key: str
    name: str
    question: str
    records: tuple[RawRecord, ...]
    verification: Verification | None
    expected: tuple[str, ...]


@dataclass
class Decision:
    eligibility: Eligibility
    evidence_fit: EvidenceFit
    trust: Trust
    reasons: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)


@dataclass
class PrototypeState:
    scenario: Scenario
    classifications: list[str] = field(default_factory=list)
    dedup_assessment: str = "NOT_RUN"
    active_claims: list[Claim] = field(default_factory=list)
    resolved_fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    verification_result: str = "NOT_RUN"
    decision: Decision | None = None
    manual_decision: str = "UNDECIDED"
    history: list[str] = field(default_factory=list)


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    kept_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"source", "from"}
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            urlencode(kept_query),
            "",
        )
    )


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def title_is_specific(title: str) -> bool:
    separators = ("、", ",", "，", "/", "；", ";")
    broad_tokens = ("岗位详见官网", "岗位族", "产品类", "研发类", "运营类", "职能类")
    return not any(token in title for token in broad_tokens) and sum(title.count(s) for s in separators) == 0


def classify_record(record: RawRecord) -> OpportunityKind:
    if record.official_job_id and title_is_specific(record.title):
        return OpportunityKind.POSTING
    if not title_is_specific(record.title) or len(record.cities) > 1:
        return OpportunityKind.CAMPAIGN
    return OpportunityKind.POSTING


def canonical_company(value: str) -> str:
    suffixes = ("有限公司", "科技有限公司", "集团", "中国")
    normalized = value.replace(" ", "").lower()
    for suffix in suffixes:
        normalized = normalized.removesuffix(suffix.lower())
    return normalized


def assess_duplicate(records: tuple[RawRecord, ...]) -> str:
    if len(records) < 2:
        return "SINGLE_RECORD"
    left, right = records[0], records[1]
    if left.official_job_id and right.official_job_id:
        if left.official_job_id == right.official_job_id:
            return "MERGE_EXACT_OFFICIAL_ID"
        return "SEPARATE_OFFICIAL_ID_CONFLICT"
    if normalize_url(left.url) and normalize_url(left.url) == normalize_url(right.url):
        return "MERGE_EXACT_OFFICIAL_URL"
    if domain(left.url) and domain(right.url) and domain(left.url) != domain(right.url):
        if left.company == right.company:
            return "REVIEW_OR_SEPARATE_DOMAIN_CONFLICT"
    company_same = canonical_company(left.company) == canonical_company(right.company)
    title_similarity = SequenceMatcher(None, left.title.lower(), right.title.lower()).ratio()
    city_overlap = bool(set(left.cities) & set(right.cities))
    if company_same and title_similarity >= 0.9 and city_overlap:
        return "REVIEW_SIMILAR_NO_STABLE_KEY"
    return "SEPARATE_INSUFFICIENT_EVIDENCE"


def record_claims(record: RawRecord) -> list[Claim]:
    observed_at = "2026-08-09"
    pairs = {
        "company": record.company,
        "title": record.title,
        "cities": record.cities,
        "graduation_years": record.graduation_years,
        "education": record.education,
        "recruitment_type": record.recruitment_type,
        "url": normalize_url(record.url),
    }
    if record.official_job_id:
        pairs["official_job_id"] = record.official_job_id
    return [
        Claim(
            field_name=field_name,
            value=value,
            source=record.source,
            authority=record.source_authority,
            observed_at=observed_at,
            evidence=f"{record.source} 原始记录",
        )
        for field_name, value in pairs.items()
    ]


def _stable_value(value: Any) -> str:
    if isinstance(value, (tuple, list, set)):
        return "|".join(sorted(str(item) for item in value))
    return str(value)


def resolve_claims(claims: list[Claim]) -> dict[str, dict[str, Any]]:
    fields: dict[str, list[Claim]] = {}
    for claim in claims:
        fields.setdefault(claim.field_name, []).append(claim)

    resolved: dict[str, dict[str, Any]] = {}
    for field_name, field_claims in fields.items():
        max_authority = max(claim.authority for claim in field_claims)
        top = [claim for claim in field_claims if claim.authority == max_authority]
        top_values = {_stable_value(claim.value) for claim in top}
        all_values = {_stable_value(claim.value) for claim in field_claims}
        if len(top_values) > 1:
            selected: Any = None
            status = "UNRESOLVED_CONFLICT"
        else:
            selected = top[-1].value
            status = "CONFLICTED_RESOLVED" if len(all_values) > 1 else "CONSISTENT"
        resolved[field_name] = {
            "value": selected,
            "status": status,
            "selected_source": top[-1].source if selected is not None else None,
            "claim_count": len(field_claims),
        }
    return resolved


def evaluate_decision(state: PrototypeState, profile: Profile | None = None) -> Decision:
    profile = profile or Profile()
    reasons: list[str] = []
    unknowns: list[str] = []

    if state.dedup_assessment.startswith("SEPARATE") or state.dedup_assessment.startswith("REVIEW"):
        return Decision(
            eligibility=Eligibility.UNKNOWN,
            evidence_fit=EvidenceFit.UNKNOWN,
            trust=Trust.UNCONFIRMED,
            reasons=["候选记录尚未确认属于同一岗位，禁止合并后计算三轴"],
            unknowns=["需要分别创建 Posting 或完成人工实体确认"],
        )

    if not state.classifications or all(kind == OpportunityKind.CAMPAIGN.value for kind in state.classifications):
        return Decision(
            eligibility=Eligibility.UNKNOWN,
            evidence_fit=EvidenceFit.UNKNOWN,
            trust=Trust.UNCONFIRMED,
            reasons=["只有招聘项目线索，尚无可单独投递的具体岗位"],
            unknowns=["具体岗位名称、城市和硬性条件"],
        )

    fields = state.resolved_fields
    failures: list[str] = []

    def value_of(name: str) -> Any:
        entry = fields.get(name)
        if not entry or entry["status"] == "UNRESOLVED_CONFLICT":
            unknowns.append(name)
            return None
        return entry["value"]

    cities = value_of("cities")
    graduation_years = value_of("graduation_years")
    education = value_of("education")
    title = value_of("title")

    if cities is not None and not set(profile.preferred_cities) & set(cities):
        failures.append(f"具体岗位城市 {', '.join(cities)} 不在首选城市中")
    if graduation_years is not None and profile.graduation_year not in graduation_years:
        failures.append(f"毕业年份不含 {profile.graduation_year}")
    if education is not None and profile.education not in education:
        failures.append(f"学历要求不含 {profile.education}")

    verification = VerificationResult(state.verification_result) if state.verification_result in VerificationResult._value2member_map_ else None
    if verification == VerificationResult.CLOSED:
        failures.append("官方证据明确岗位已关闭")
    elif verification in {VerificationResult.NOT_FOUND, VerificationResult.BLOCKED, VerificationResult.UNKNOWN}:
        unknowns.append("岗位当前开放状态")
    elif verification is None:
        unknowns.append("尚未核验官方状态")

    if failures:
        eligibility = Eligibility.FAIL
        reasons.extend(failures)
    elif unknowns:
        eligibility = Eligibility.UNKNOWN
        reasons.append("没有明确不符合项，但仍存在关键未知")
    else:
        eligibility = Eligibility.PASS
        reasons.append("已核验硬条件均满足")

    if title:
        keyword_hits = [keyword for keyword in profile.target_keywords if keyword.lower() in str(title).lower()]
        evidence_fit = EvidenceFit.HIGH if len(keyword_hits) >= 2 else EvidenceFit.MEDIUM if keyword_hits else EvidenceFit.LOW
        reasons.append(f"岗位方向证据命中：{', '.join(keyword_hits) if keyword_hits else '无'}")
    else:
        evidence_fit = EvidenceFit.UNKNOWN

    has_conflict = any(entry["status"] != "CONSISTENT" for entry in fields.values())
    if verification == VerificationResult.OPEN:
        trust = Trust.VERIFIED_WITH_CONFLICT if has_conflict else Trust.VERIFIED
    elif verification in {VerificationResult.NOT_FOUND, VerificationResult.BLOCKED, VerificationResult.UNKNOWN}:
        trust = Trust.UNCONFIRMED
    elif has_conflict:
        trust = Trust.CONFLICTED
    else:
        trust = Trust.CONSISTENT if len(state.scenario.records) > 1 else Trust.UNCONFIRMED

    return Decision(
        eligibility=eligibility,
        evidence_fit=evidence_fit,
        trust=trust,
        reasons=reasons,
        unknowns=sorted(set(unknowns)),
    )


def scenarios() -> tuple[Scenario, ...]:
    agg = Authority.AGGREGATOR
    official = Authority.OFFICIAL_POSTING
    return (
        Scenario(
            key="1",
            name="多岗位 × 多城市招聘活动",
            question="是否会错误生成多个具体岗位？",
            records=(
                RawRecord("供应商A", "字节跳动", "产品类、算法类、运营类，岗位详见官网", ("上海", "杭州", "深圳"), ("2027届",), ("本科", "硕士"), "秋招", "https://jobs.bytedance.com/campus"),
            ),
            verification=None,
            expected=("分类为 CAMPAIGN", "不生成 9 个 Posting", "Eligibility=UNKNOWN"),
        ),
        Scenario(
            key="2",
            name="带具体职位 ID 的官方岗位",
            question="出现校招字样时是否仍能识别具体岗位？",
            records=(
                RawRecord("官方职位页", "字节跳动", "豆包大模型AI产品实习生", ("上海",), ("2027届",), ("本科", "硕士"), "实习", "https://jobs.bytedance.com/campus/position/A110957", "A110957", official),
            ),
            verification=Verification(
                VerificationResult.OPEN,
                "2026-08-09",
                "https://jobs.bytedance.com/campus/position/A110957",
                evidence="官方具体职位页可访问",
            ),
            expected=("分类为 POSTING", "状态 OPEN", "可进入三轴决策"),
        ),
        Scenario(
            key="3",
            name="两来源同一具体岗位",
            question="原始记录保留的同时能否精确合并？",
            records=(
                RawRecord("供应商A", "字节跳动", "AI产品经理（豆包）", ("上海",), ("2027届",), ("硕士",), "秋招", "https://jobs.bytedance.com/job/A1001?utm_source=a", "A1001", agg),
                RawRecord("供应商B", "北京字节跳动科技有限公司", "AI 产品经理(豆包)", ("上海",), ("2027届",), ("硕士",), "秋招", "https://jobs.bytedance.com/job/A1001", "A1001", agg),
            ),
            verification=Verification(
                VerificationResult.OPEN,
                "2026-08-09",
                "https://jobs.bytedance.com/job/A1001",
                claims=(
                    Claim("company", "字节跳动", "官方具体职位页", official, "2026-08-09", "官方职位主体"),
                    Claim("title", "AI产品经理（豆包）", "官方具体职位页", official, "2026-08-09", "官方职位名称"),
                ),
                evidence="同一官方职位 ID",
            ),
            expected=("MERGE_EXACT_OFFICIAL_ID", "两条 RawRecord 均保留", "合并为一个 Posting"),
        ),
        Scenario(
            key="4",
            name="同公司同标题但不同岗位 ID",
            question="是否会把同名不同岗错误合并？",
            records=(
                RawRecord("供应商A", "示例科技", "AI产品经理", ("上海",), ("2027届",), ("硕士",), "秋招", "https://jobs.example.com/job/1001", "1001", agg),
                RawRecord("供应商B", "示例科技", "AI产品经理", ("杭州",), ("2027届",), ("硕士",), "秋招", "https://jobs.example.com/job/1002", "1002", agg),
            ),
            verification=None,
            expected=("SEPARATE_OFFICIAL_ID_CONFLICT", "保留两个 Posting", "投递状态分别维护"),
        ),
        Scenario(
            key="5",
            name="同名公司但官网域名不同",
            question="是否会仅按公司名和标题合并？",
            records=(
                RawRecord("供应商A", "星辰科技", "产品经理", ("上海",), ("2027届",), ("硕士",), "秋招", "https://jobs.star-a.com/job/1"),
                RawRecord("供应商B", "星辰科技", "产品经理", ("上海",), ("2027届",), ("硕士",), "秋招", "https://careers.star-b.cn/job/9"),
            ),
            verification=None,
            expected=("REVIEW_OR_SEPARATE_DOMAIN_CONFLICT", "不得自动合并", "需要公司实体人工确认"),
        ),
        Scenario(
            key="6",
            name="供应商冲突，官网给出明确值",
            question="能否按字段采用当前官网证据并保留历史冲突？",
            records=(
                RawRecord("供应商A", "示例智能", "AI产品经理", ("上海",), ("2027届",), ("硕士",), "秋招", "https://jobs.example.ai/100", "100", agg),
                RawRecord("供应商B", "示例智能", "AI产品经理", ("上海", "杭州"), ("2027届",), ("硕士",), "秋招", "https://jobs.example.ai/100", "100", agg),
            ),
            verification=Verification(
                VerificationResult.OPEN,
                "2026-08-09",
                "https://jobs.example.ai/100",
                claims=(
                    Claim("cities", ("上海",), "官方具体职位页", official, "2026-08-09", "工作地点：上海"),
                ),
                evidence="官方岗位仍开放",
            ),
            expected=("显示值采用官方上海", "历史冲突仍可见", "Trust=VERIFIED_WITH_CONFLICT"),
        ),
        Scenario(
            key="7",
            name="官网开放但未声明毕业年份",
            question="官网缺字段时是否会错误覆盖供应商冲突？",
            records=(
                RawRecord("供应商A", "示例平台", "数据产品经理", ("上海",), ("2027届",), ("硕士",), "秋招", "https://jobs.example.io/77", "77", agg),
                RawRecord("供应商B", "示例平台", "数据产品经理", ("上海",), ("2026届", "2027届"), ("硕士",), "秋招", "https://jobs.example.io/77", "77", agg),
            ),
            verification=Verification(VerificationResult.OPEN, "2026-08-09", "https://jobs.example.io/77", evidence="官网开放，但未写毕业窗口"),
            expected=("毕业年份保持冲突", "Eligibility=UNKNOWN", "进入待确认队列"),
        ),
        Scenario(
            key="8",
            name="官方链接今日无法找到",
            question="是否会把 NOT_FOUND 错误等同 CLOSED？",
            records=(
                RawRecord("供应商A", "示例机器人", "AI解决方案产品经理", ("上海",), ("2027届",), ("硕士",), "秋招", "https://jobs.example-robot.com/404", "404", agg),
            ),
            verification=Verification(VerificationResult.NOT_FOUND, "2026-08-09", "https://jobs.example-robot.com/404", evidence="今日返回404，没有官方关闭文案"),
            expected=("状态 NOT_FOUND 而非 CLOSED", "Eligibility=UNKNOWN", "需要人工复核"),
        ),
    )


def initial_state(scenario: Scenario) -> PrototypeState:
    claims: list[Claim] = []
    for record in scenario.records:
        claims.extend(record_claims(record))
    return PrototypeState(scenario=scenario, active_claims=claims)


def reduce_state(state: PrototypeState, action: str) -> PrototypeState:
    next_state = deepcopy(state)
    if action == "classify":
        next_state.classifications = [classify_record(record).value for record in state.scenario.records]
        next_state.history.append("已分类原始记录")
    elif action == "deduplicate":
        next_state.dedup_assessment = assess_duplicate(state.scenario.records)
        next_state.history.append("已评估重复关系")
    elif action == "verify":
        verification = state.scenario.verification
        if verification is None:
            next_state.verification_result = VerificationResult.UNKNOWN.value
            next_state.history.append("没有具体官网证据，保持 UNKNOWN")
        else:
            next_state.verification_result = verification.result.value
            next_state.active_claims.extend(verification.claims)
            next_state.history.append(f"已应用官网核验：{verification.result.value}")
        next_state.resolved_fields = resolve_claims(next_state.active_claims)
    elif action == "evaluate":
        if not next_state.resolved_fields:
            next_state.resolved_fields = resolve_claims(next_state.active_claims)
        next_state.decision = evaluate_decision(next_state)
        next_state.history.append("已计算三轴决策")
    elif action == "manual":
        order = ("UNDECIDED", "APPLY", "VERIFY_FIRST", "HOLD", "REJECT")
        index = (order.index(next_state.manual_decision) + 1) % len(order)
        next_state.manual_decision = order[index]
        next_state.history.append(f"人工结论改为 {next_state.manual_decision}")
    elif action == "all":
        for nested in ("classify", "deduplicate", "verify", "evaluate"):
            next_state = reduce_state(next_state, nested)
    return next_state


def state_snapshot(state: PrototypeState) -> dict[str, Any]:
    decision = asdict(state.decision) if state.decision else None
    if decision:
        decision["eligibility"] = state.decision.eligibility.value
        decision["evidence_fit"] = state.decision.evidence_fit.value
        decision["trust"] = state.decision.trust.value
    return {
        "scenario": {"key": state.scenario.key, "name": state.scenario.name, "question": state.scenario.question},
        "raw_records": [
            {
                "source": record.source,
                "company": record.company,
                "title": record.title,
                "cities": list(record.cities),
                "official_job_id": record.official_job_id,
            }
            for record in state.scenario.records
        ],
        "classifications": state.classifications,
        "dedup_assessment": state.dedup_assessment,
        "verification_result": state.verification_result,
        "resolved_fields": state.resolved_fields,
        "decision": decision,
        "manual_decision": state.manual_decision,
        "history": state.history,
        "expected": list(state.scenario.expected),
    }
