from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

SPACE_PATTERN = re.compile(r"\s+")
URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
TEXT_JOB_ID_PATTERN = re.compile(
    r"职位\s*ID\s*[:：]?\s*([A-Za-z0-9_-]{3,})", re.IGNORECASE
)
GENERIC_JOB_ID_TOKENS = {
    "career",
    "careers",
    "campus",
    "detail",
    "graduate",
    "graduates",
    "home",
    "index",
    "job",
    "jobs",
    "list",
    "opening",
    "openings",
    "position",
    "positions",
    "program",
    "recruitment",
    "search",
    "student",
    "students",
}
GENERIC_JOB_ID_FRAGMENTS = {
    "campus",
    "earlycareer",
    "early-career",
    "graduate",
    "program",
    "recruit",
    "student",
}
COMPANY_SUFFIXES = (
    "股份有限公司",
    "有限责任公司",
    "科技有限公司",
    "有限公司",
    "集团股份",
    "集团",
)
VALUE_SEPARATORS = re.compile(r"[、，,；;/|]+")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return SPACE_PATTERN.sub(" ", str(value).replace("\u3000", " ")).strip()


def extract_url(value: Any) -> str:
    text = clean_text(value)
    match = URL_PATTERN.search(text)
    return normalize_url(match.group(0)) if match else ""


def normalize_url(value: Any) -> str:
    text = clean_text(value).strip("<>")
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"}:
        return ""
    ignored = {"source", "from", "share", "shareid", "track", "channel"}
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in ignored
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower().removeprefix("www."),
            re.sub(r"/{2,}", "/", parsed.path).rstrip("/"),
            "",
            urlencode(sorted(query)),
            "",
        )
    )


def normalize_company(value: Any) -> str:
    normalized = clean_text(value).replace(" ", "").lower()
    for suffix in COMPANY_SUFFIXES:
        if normalized.endswith(suffix.lower()) and len(normalized) > len(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def split_values(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    parts = [clean_text(item) for item in VALUE_SEPARATORS.split(text)]
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            result.append(part)
    return result


def is_plausible_official_job_id(value: Any) -> bool:
    """Reject broad campaign tokens that cannot safely identify one posting."""

    candidate = clean_text(value).casefold()
    if not candidate or not re.fullmatch(r"[a-z0-9_-]{2,255}", candidate):
        return False
    if re.fullmatch(r"(?:19|20)\d{2}", candidate):
        return False
    if candidate in GENERIC_JOB_ID_TOKENS:
        return False
    return not any(fragment in candidate for fragment in GENERIC_JOB_ID_FRAGMENTS)


def extract_official_job_id(*values: Any) -> str | None:
    specific_containers = {
        "position",
        "positions",
        "job",
        "jobs",
        "openings",
        "jobdetail",
        "job-detail",
    }
    unsafe_contexts = {
        "about",
        "article",
        "campus",
        "graduate",
        "news",
        "program",
        "recruitment",
    }
    explicit_query_keys = {
        "job_id",
        "jobid",
        "position_id",
        "positionid",
        "posting_id",
        "postingid",
    }
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        textual = TEXT_JOB_ID_PATTERN.search(text)
        if textual and is_plausible_official_job_id(textual.group(1)):
            return textual.group(1)
        for candidate_url in URL_PATTERN.findall(text):
            normalized = normalize_url(candidate_url)
            parsed = urlparse(normalized)
            segments = [
                segment.strip() for segment in parsed.path.split("/") if segment.strip()
            ]
            lowered = [segment.lower() for segment in segments]
            if any(segment in unsafe_contexts for segment in lowered):
                continue
            for index in range(len(segments) - 1):
                candidate = segments[index + 1]
                if (
                    lowered[index] in specific_containers
                    and re.fullmatch(r"[A-Za-z0-9_-]{4,}", candidate)
                    and is_plausible_official_job_id(candidate)
                ):
                    return candidate
            query = parse_qs(parsed.query, keep_blank_values=True)
            for key, query_values in query.items():
                if key.lower() not in explicit_query_keys:
                    continue
                for candidate in query_values:
                    if re.fullmatch(
                        r"[A-Za-z0-9_-]{4,}", candidate
                    ) and is_plausible_official_job_id(candidate):
                        return candidate
            if any(segment in specific_containers for segment in lowered):
                for key, query_values in query.items():
                    if key.lower() != "id":
                        continue
                    for candidate in query_values:
                        if re.fullmatch(
                            r"[A-Za-z0-9_-]{4,}", candidate
                        ) and is_plausible_official_job_id(candidate):
                            return candidate
    return None


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any, length: int = 64) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()[:length]


def compound_identity_hint(
    company: str,
    title: str,
    cities: Iterable[str],
    recruitment_type: str,
    graduation_years: Iterable[str],
) -> str | None:
    parts = {
        "company": normalize_company(company),
        "title": clean_text(title).lower(),
        "cities": sorted(clean_text(city) for city in cities if clean_text(city)),
        "recruitment_type": clean_text(recruitment_type).lower(),
        "graduation_years": sorted(
            clean_text(year) for year in graduation_years if clean_text(year)
        ),
    }
    if not parts["company"] or not parts["title"]:
        return None
    return digest(parts, length=32)
