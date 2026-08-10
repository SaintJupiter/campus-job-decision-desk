from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from publicsuffix2 import get_tld
from sqlalchemy import select
from sqlalchemy.orm import Session

from campus_job_desk.domain.classify import (
    looks_like_direct_posting_url,
    official_job_id_matches_url,
)
from campus_job_desk.domain.enums import Authority, FieldName, OpportunityKind, VerificationResult
from campus_job_desk.domain.normalize import normalize_url, stable_json
from campus_job_desk.models import FieldClaim, Opportunity, VerificationAttempt
from campus_job_desk.repositories.opportunities import refresh_claim_selection
from campus_job_desk.services.events import record_event

AGGREGATOR_DOMAINS = (
    "offercoming.cn",
    "offerbiu.com",
    "nowcoder.com",
    "shixiseng.com",
    "zhipin.com",
    "51job.com",
    "zhaopin.com",
    "jobui.com",
    "liepin.com",
    "mp.weixin.qq.com",
    "weixin.qq.com",
    "docs.qq.com",
    "feishu.cn",
    "notion.site",
    "github.io",
    "vercel.app",
    "netlify.app",
    "pages.dev",
    "web.app",
)
SHARED_ATS_DOMAINS = {
    "apply.workable.com",
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.ashbyhq.com",
    "jobs.lever.co",
    "jobs.smartrecruiters.com",
}
SHARED_ATS_PARENT_DOMAINS = {
    "ashbyhq.com",
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "myworkdaysite.com",
    "smartrecruiters.com",
    "workable.com",
}
WORKDAY_INFRASTRUCTURE_DOMAIN = re.compile(
    r"^wd\d+\.(?:myworkdayjobs|myworkdaysite)\.com$"
)
USER_VERIFIABLE_FIELDS = {
    FieldName.CITIES.value,
    FieldName.GRADUATION_YEARS.value,
    FieldName.EDUCATION.value,
    FieldName.RECRUITMENT_TYPE.value,
    FieldName.DEADLINE.value,
}


class VerificationValidationError(ValueError):
    pass


def normalize_official_domain(value: str) -> str:
    return normalize_official_scope(value)[0]


def normalize_official_scope(value: str) -> tuple[str, str]:
    candidate = value.strip()
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or "").lower().rstrip(".").removeprefix("www.")
    if not host or len(host) > 253 or not re.fullmatch(r"[a-z0-9.-]+", host):
        raise VerificationValidationError("官方域名格式无效")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise VerificationValidationError("IP 地址不能作为官方招聘域名")
    if get_tld(host, strict=True) in {None, host}:
        raise VerificationValidationError("公共后缀或单标签不能作为官方招聘域名")
    if any(host == item or host.endswith(f".{item}") for item in AGGREGATOR_DOMAINS):
        raise VerificationValidationError("聚合平台域名不能确认为公司官方招聘域名")
    if host in SHARED_ATS_PARENT_DOMAINS or WORKDAY_INFRASTRUCTURE_DOMAIN.fullmatch(host):
        raise VerificationValidationError(
            "共享 ATS 父域不能作为单家公司官网；请提供包含公司租户的招聘页面 URL"
        )
    scope_path = ""
    if host in SHARED_ATS_DOMAINS:
        segments = [segment for segment in parsed.path.split("/") if segment]
        if not segments:
            raise VerificationValidationError(
                "共享 ATS 域名必须提供包含公司租户路径的招聘页面 URL"
            )
        scope_path = f"/{segments[0].casefold()}"
    return host, scope_path


def _scope_matches(opportunity: Opportunity, url: str) -> bool:
    if not opportunity.organization or not opportunity.organization.official_domain_verified:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".").removeprefix("www.")
    trusted_domain = opportunity.organization.official_domain.casefold()
    if host != trusted_domain and not host.endswith(f".{trusted_domain}"):
        return False
    trusted_path = opportunity.organization.official_scope_path.casefold().rstrip("/")
    if trusted_domain in SHARED_ATS_DOMAINS:
        path = "/" + "/".join(segment.casefold() for segment in parsed.path.split("/") if segment)
        return bool(
            trusted_path
            and (path == trusted_path or path.startswith(f"{trusted_path}/"))
        )
    return True


def effective_verification(
    session: Session,
    opportunity: Opportunity,
) -> Optional[VerificationAttempt]:
    if not opportunity.organization or not opportunity.organization.official_domain_verified:
        return None
    attempts = list(
        session.scalars(
        select(VerificationAttempt)
        .where(
            VerificationAttempt.opportunity_id == opportunity.id,
            VerificationAttempt.evidence_scope == opportunity.kind,
            VerificationAttempt.verified_domain
            == opportunity.organization.official_domain,
            VerificationAttempt.verified_scope_path
            == opportunity.organization.official_scope_path,
        )
        .order_by(
            VerificationAttempt.checked_at.desc(),
            VerificationAttempt.created_at.desc(),
            VerificationAttempt.id.desc(),
        )
        )
    )
    for attempt in attempts:
        if opportunity.kind == OpportunityKind.POSTING.value:
            if not opportunity.official_job_id:
                return None
            if not official_job_id_matches_url(
                attempt.final_url or attempt.url,
                opportunity.official_job_id,
            ):
                continue
        return attempt
    return None


def validate_official_identity_url(
    opportunity: Opportunity,
    *,
    url: str,
    official_job_id: str,
) -> str:
    canonical_url = normalize_url(url)
    parsed = urlparse(canonical_url)
    host = (parsed.hostname or "").lower().rstrip(".").removeprefix("www.")
    if any(host == item or host.endswith(f".{item}") for item in AGGREGATOR_DOMAINS):
        raise VerificationValidationError("聚合平台链接不能用于绑定官方岗位身份")
    trusted_domain = (
        opportunity.organization.official_domain.lower().rstrip(".").removeprefix("www.")
        if opportunity.organization and opportunity.organization.official_domain_verified
        else ""
    )
    if not trusted_domain:
        raise VerificationValidationError("请先确认公司官方招聘域名")
    if not _scope_matches(opportunity, canonical_url):
        raise VerificationValidationError("岗位身份链接与已确认官网域名或租户路径不匹配")
    if not official_job_id_matches_url(canonical_url, official_job_id):
        raise VerificationValidationError("链接未在岗位路径或明确 ID 参数中精确匹配该岗位 ID")
    return canonical_url


def record_verification(
    session: Session,
    *,
    opportunity_id: str,
    result: VerificationResult,
    url: str,
    final_url: str = "",
    checked_at: Optional[datetime] = None,
    evidence_excerpt: str = "",
    extracted_fields: Optional[dict[str, Any]] = None,
    reviewer: str = "user",
) -> VerificationAttempt:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise VerificationValidationError("未找到岗位")
    canonical_url = normalize_url(final_url or url)
    if not canonical_url:
        raise VerificationValidationError("核验 URL 无效")
    _validate_official_evidence(
        opportunity,
        result=result,
        url=canonical_url,
        evidence_excerpt=evidence_excerpt,
    )
    if result not in {VerificationResult.OPEN, VerificationResult.CLOSED} and extracted_fields:
        raise VerificationValidationError(
            "页面未找到、访问受阻或未知状态不能写入官网字段 claim"
        )
    observed_at = checked_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    else:
        observed_at = observed_at.astimezone(timezone.utc)
    if observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise VerificationValidationError("核验时间不能晚于当前时间")
    verified_fields = _sanitize_extracted_fields(extracted_fields or {})
    if result in {VerificationResult.OPEN, VerificationResult.CLOSED}:
        verified_fields[FieldName.STATUS.value] = result.value
        if opportunity.kind == OpportunityKind.POSTING.value:
            verified_fields[FieldName.APPLY_URL.value] = canonical_url
    attempt = VerificationAttempt(
        opportunity_id=opportunity_id,
        result=result.value,
        evidence_scope=opportunity.kind,
        verified_domain=(
            opportunity.organization.official_domain.lower().rstrip(".")
            if opportunity.organization
            else ""
        ),
        verified_scope_path=(
            opportunity.organization.official_scope_path
            if opportunity.organization
            else ""
        ),
        url=normalize_url(url),
        final_url=normalize_url(final_url),
        checked_at=observed_at,
        evidence_excerpt=evidence_excerpt.strip(),
        content_hash=hashlib.sha256(evidence_excerpt.strip().encode()).hexdigest()
        if evidence_excerpt.strip()
        else "",
        extracted_fields=json.dumps(verified_fields, ensure_ascii=False, sort_keys=True),
        reviewer=reviewer,
    )
    session.add(attempt)
    session.flush()
    _add_verified_claims(session, opportunity, attempt, verified_fields)
    record_event(
        session,
        entity_type="opportunity",
        entity_id=opportunity_id,
        event_type="VERIFICATION_RECORDED",
        payload={
            "verification_id": attempt.id,
            "result": attempt.result,
            "checked_at": observed_at.isoformat(),
            "field_names": sorted(verified_fields),
        },
    )
    return attempt


def _validate_official_evidence(
    opportunity: Opportunity,
    *,
    result: VerificationResult,
    url: str,
    evidence_excerpt: str,
) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".").removeprefix("www.")
    if any(host == item or host.endswith(f".{item}") for item in AGGREGATOR_DOMAINS):
        raise VerificationValidationError("聚合平台链接不能作为官网核验证据")
    trusted_domain = ""
    if opportunity.organization and opportunity.organization.official_domain_verified:
        trusted_domain = (
            opportunity.organization.official_domain.lower()
            .rstrip(".")
            .removeprefix("www.")
        )
    if not trusted_domain:
        raise VerificationValidationError("公司官方招聘域名未知，不能直接标记为官网已核验")
    if not _scope_matches(opportunity, url):
        raise VerificationValidationError("核验链接与岗位官网域名或公司租户路径不匹配")
    if result not in {VerificationResult.OPEN, VerificationResult.CLOSED}:
        return
    if len(evidence_excerpt.strip()) < 5:
        raise VerificationValidationError("在招或关闭结论必须保存可复核的页面证据摘录")
    if opportunity.kind == OpportunityKind.POSTING.value:
        if not opportunity.official_job_id:
            raise VerificationValidationError(
                "具体岗位尚未绑定官方岗位 ID，请先确认岗位身份"
            )
        direct_url = looks_like_direct_posting_url(url, opportunity.official_job_id)
        if not direct_url:
            raise VerificationValidationError("核验页未结构化匹配当前岗位的官方 ID")


def _add_verified_claims(
    session: Session,
    opportunity: Opportunity,
    attempt: VerificationAttempt,
    extracted_fields: dict[str, Any],
) -> None:
    allowed = USER_VERIFIABLE_FIELDS | {
        FieldName.STATUS.value,
        FieldName.APPLY_URL.value,
    }
    authority = (
        int(Authority.OFFICIAL_CAMPAIGN)
        if opportunity.kind == OpportunityKind.CAMPAIGN.value
        else int(Authority.OFFICIAL_POSTING)
    )
    created_fields: set[str] = set()
    for field_name, value in extracted_fields.items():
        if field_name not in allowed or value in (None, "", []):
            continue
        session.add(
            FieldClaim(
                opportunity_id=opportunity.id,
                verification_id=attempt.id,
                field_name=field_name,
                raw_value=stable_json(value),
                normalized_value=stable_json(value),
                authority=authority,
                observed_at=attempt.checked_at,
                evidence_label="官网人工核验",
                evidence_url=attempt.final_url or attempt.url,
                parser="manual-verification",
                parser_version="v2",
                confidence=1.0,
                selected=False,
                resolution_reason="",
            )
        )
        created_fields.add(field_name)
    session.flush()
    for field_name in created_fields:
        refresh_claim_selection(session, opportunity.id, field_name)
    from campus_job_desk.services.workflow import invalidate_decisions

    invalidate_decisions(session, opportunity_ids=[opportunity.id])


def _sanitize_extracted_fields(fields: dict[str, Any]) -> dict[str, Any]:
    unsupported = sorted(set(fields) - USER_VERIFIABLE_FIELDS)
    if unsupported:
        raise VerificationValidationError(
            "核验接口不允许写入受保护字段：" + "、".join(unsupported)
        )
    sanitized: dict[str, Any] = {}
    for field_name, value in fields.items():
        if value in (None, "", []):
            continue
        if field_name in {
            FieldName.CITIES.value,
            FieldName.GRADUATION_YEARS.value,
            FieldName.EDUCATION.value,
        }:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise VerificationValidationError(f"{field_name} 必须是字符串数组")
            sanitized[field_name] = [item.strip()[:100] for item in value[:30] if item.strip()]
        else:
            if not isinstance(value, str):
                raise VerificationValidationError(f"{field_name} 必须是字符串")
            sanitized[field_name] = value.strip()[:300]
    return sanitized
