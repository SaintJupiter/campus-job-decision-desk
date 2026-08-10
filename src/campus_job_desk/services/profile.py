from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader

from campus_job_desk.domain.enums import ProfileFactKind, ResumeFormat
from campus_job_desk.domain.profile import (
    EvidenceProfile,
    EvidenceSpan,
    FactProvenance,
    JobPreferences,
    ProfileFact,
)


class ResumeContentProvider(Protocol):
    def extract(self, content: bytes) -> str: ...


class PlainTextProvider:
    def extract(self, content: bytes) -> str:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("resume text must be UTF-8 or GB18030 encoded")


class PdfTextProvider:
    def extract(self, content: bytes) -> str:
        reader = PdfReader(io.BytesIO(content))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        text = "\n\n".join(page for page in pages if page)
        if not text:
            raise ValueError("PDF contains no extractable text")
        return text


EDUCATION_PATTERNS = (
    ("\u535a\u58eb", re.compile(r"\u535a\u58eb|Ph\.?D", re.IGNORECASE)),
    ("\u7855\u58eb", re.compile(r"\u7855\u58eb|\u7814\u7a76\u751f|Master", re.IGNORECASE)),
    ("\u672c\u79d1", re.compile(r"\u672c\u79d1|\u5b66\u58eb|Bachelor", re.IGNORECASE)),
    ("\u5927\u4e13", re.compile(r"\u5927\u4e13|\u4e13\u79d1")),
)
CAPABILITY_PATTERNS = {
    "Python": re.compile(r"(?<![A-Za-z0-9])Python(?![A-Za-z0-9])", re.IGNORECASE),
    "SQL": re.compile(r"(?<![A-Za-z0-9])SQL(?![A-Za-z0-9])", re.IGNORECASE),
    "AI": re.compile(
        r"(?<![A-Za-z0-9])AI(?![A-Za-z0-9])|\u4eba\u5de5\u667a\u80fd|\u5927\u6a21\u578b|\u673a\u5668\u5b66\u4e60",
        re.IGNORECASE,
    ),
    "\u4ea7\u54c1": re.compile(r"\u4ea7\u54c1\u7ecf\u7406|\u9700\u6c42\u5206\u6790|\u7528\u6237\u8c03\u7814|\bPRD\b|\u539f\u578b", re.IGNORECASE),
    "\u6570\u636e": re.compile(r"\u6570\u636e\u5206\u6790|\u6570\u636e\u5904\u7406|\u6307\u6807\u4f53\u7cfb|\u6570\u636e\u5e73\u53f0"),
    "\u5e73\u53f0": re.compile(r"\u5e73\u53f0|\u4e2d\u53f0|\u5f00\u53d1\u8005\u670d\u52a1"),
    "\u89e3\u51b3\u65b9\u6848": re.compile(r"\u89e3\u51b3\u65b9\u6848|\u6280\u672f\u54a8\u8be2|\u884c\u4e1a\u65b9\u6848"),
    "\u4eff\u771f": re.compile(r"\u4eff\u771f|\u6570\u5b57\u5b6a\u751f|\bSIL\b|\bHIL\b", re.IGNORECASE),
    "\u6d4b\u8bd5\u8bc4\u6d4b": re.compile(r"\u6d4b\u8bd5|\u8bc4\u6d4b|\u8bc4\u4f30|\u8d28\u91cf"),
}
GRADUATION_PATTERNS = (
    re.compile(r"(?P<year>(?:19|20)\d{2})\s*\u5c4a"),
    re.compile(r"(?:\u9884\u8ba1\s*)?(?P<year>(?:19|20)\d{2})\s*\u5e74\s*(?:\u9884\u8ba1\s*)?\u6bd5\u4e1a"),
    re.compile(
        r"(?:\u9884\u8ba1\s*)?(?P<year>(?:19|20)\d{2})\s*(?:[./-]|\u5e74)\s*\d{1,2}\s*\u6708?\s*\u6bd5\u4e1a"
    ),
    re.compile(r"\u6bd5\u4e1a\u65f6\u95f4\s*[:\uff1a]?\s*(?P<year>(?:19|20)\d{2})"),
)
PROJECT_LINE_PATTERN = re.compile(r"项目|平台|系统|原型|产品")
EXPERIENCE_LINE_PATTERN = re.compile(
    r"负责|参与|设计|梳理|分析|搭建|实现|调研|推进|迭代|评测|验证"
)


class ProfileService:
    def __init__(self) -> None:
        self.providers: dict[ResumeFormat, ResumeContentProvider] = {
            ResumeFormat.TEXT: PlainTextProvider(),
            ResumeFormat.MARKDOWN: PlainTextProvider(),
            ResumeFormat.PDF: PdfTextProvider(),
        }

    def extract_file(
        self,
        path: str | Path,
        preferences: JobPreferences | None = None,
    ) -> EvidenceProfile:
        resume_path = Path(path)
        resume_format = self._format_for_name(resume_path.name)
        return self.extract_bytes(
            resume_path.read_bytes(),
            file_name=resume_path.name,
            resume_format=resume_format,
            preferences=preferences,
        )

    def extract_bytes(
        self,
        content: bytes,
        *,
        file_name: str,
        resume_format: ResumeFormat | None = None,
        preferences: JobPreferences | None = None,
    ) -> EvidenceProfile:
        detected_format = resume_format or self._format_for_name(file_name)
        text = self.providers[detected_format].extract(content)
        return self.extract_text(
            text,
            source_name=file_name,
            source_format=detected_format,
            preferences=preferences,
        )

    def extract_text(
        self,
        text: str,
        *,
        source_name: str = "resume.txt",
        source_format: ResumeFormat = ResumeFormat.TEXT,
        preferences: JobPreferences | None = None,
    ) -> EvidenceProfile:
        facts: list[ProfileFact] = []
        seen: set[tuple[ProfileFactKind, str, int, int]] = set()
        provenance = FactProvenance(
            source_name=source_name,
            extraction_method="deterministic-resume-extractor.v1",
        )

        for line_match in re.finditer(r"[^\r\n]+", text):
            raw_line = line_match.group(0)
            leading = len(raw_line) - len(raw_line.lstrip(" \t#-*\u2022"))
            trailing = len(raw_line) - len(raw_line.rstrip())
            start = line_match.start() + leading
            end = line_match.end() - trailing
            if end <= start:
                continue
            evidence_text = text[start:end]

            graduation = next(
                (match for pattern in GRADUATION_PATTERNS if (match := pattern.search(evidence_text))),
                None,
            )
            if graduation:
                value = graduation.group("year") + "\u5c4a"
                self._append_fact(
                    facts,
                    seen,
                    ProfileFactKind.GRADUATION_YEAR,
                    value,
                    evidence_text,
                    start,
                    end,
                    provenance,
                )

            for value, pattern in EDUCATION_PATTERNS:
                if pattern.search(evidence_text):
                    self._append_fact(
                        facts,
                        seen,
                        ProfileFactKind.EDUCATION,
                        value,
                        evidence_text,
                        start,
                        end,
                        provenance,
                    )

            for value, pattern in CAPABILITY_PATTERNS.items():
                if pattern.search(evidence_text):
                    self._append_fact(
                        facts,
                        seen,
                        ProfileFactKind.SKILL,
                        value,
                        evidence_text,
                        start,
                        end,
                        provenance,
                    )

            if len(evidence_text) >= 14 and PROJECT_LINE_PATTERN.search(evidence_text):
                self._append_fact(
                    facts,
                    seen,
                    ProfileFactKind.PROJECT,
                    self._fact_label(evidence_text, "项目证据"),
                    evidence_text,
                    start,
                    end,
                    provenance,
                )

            if len(evidence_text) >= 14 and EXPERIENCE_LINE_PATTERN.search(evidence_text):
                self._append_fact(
                    facts,
                    seen,
                    ProfileFactKind.EXPERIENCE,
                    self._fact_label(evidence_text, "经历证据"),
                    evidence_text,
                    start,
                    end,
                    provenance,
                )

        warnings = [] if facts else ["\u672a\u4ece\u7b80\u5386\u6587\u672c\u4e2d\u62bd\u53d6\u5230\u53ef\u786e\u8ba4\u4e8b\u5b9e"]
        return EvidenceProfile(
            source_name=source_name,
            source_format=source_format,
            raw_text=text,
            facts=facts,
            preferences=preferences or JobPreferences(),
            parser_warnings=warnings,
        )

    def confirm_facts(
        self,
        profile: EvidenceProfile,
        fact_ids: set[str],
    ) -> EvidenceProfile:
        facts = [
            fact.model_copy(update={"confirmed": True}) if fact.fact_id in fact_ids else fact
            for fact in profile.facts
        ]
        return profile.model_copy(update={"facts": facts})

    @staticmethod
    def _append_fact(
        facts: list[ProfileFact],
        seen: set[tuple[ProfileFactKind, str, int, int]],
        kind: ProfileFactKind,
        value: str,
        evidence_text: str,
        start: int,
        end: int,
        provenance: FactProvenance,
    ) -> None:
        key = (kind, value, start, end)
        if key in seen:
            return
        seen.add(key)
        digest = hashlib.sha256(
            f"{provenance.source_name}:{start}:{end}:{kind.value}:{value}".encode()
        ).hexdigest()[:16]
        facts.append(
            ProfileFact(
                fact_id=f"fact_{digest}",
                kind=kind,
                value=value,
                evidence_text=evidence_text,
                span=EvidenceSpan(start=start, end=end),
                provenance=provenance,
                confirmed=False,
            )
        )

    @staticmethod
    def _format_for_name(file_name: str) -> ResumeFormat:
        suffix = Path(file_name).suffix.lower()
        if suffix == ".pdf":
            return ResumeFormat.PDF
        if suffix in {".md", ".markdown"}:
            return ResumeFormat.MARKDOWN
        if suffix in {".txt", ""}:
            return ResumeFormat.TEXT
        raise ValueError(f"unsupported resume format: {suffix}")

    @staticmethod
    def _fact_label(evidence_text: str, fallback: str) -> str:
        cleaned = re.sub(r"^[#>*•\-\s]+", "", evidence_text).strip()
        heading = re.split(r"[：:]", cleaned, maxsplit=1)[0].strip()
        if 2 <= len(heading) <= 28:
            return heading
        if cleaned:
            return cleaned[:28].rstrip("，。；; ") + ("…" if len(cleaned) > 28 else "")
        return fallback
