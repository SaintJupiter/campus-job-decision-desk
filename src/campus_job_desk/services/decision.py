from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from campus_job_desk.domain.decisions import (
    DecisionBundle,
    DecisionReason,
    DecisionUnknown,
    EligibilityDecision,
    EvidenceFitDecision,
    JobDecisionContext,
    TrustDecision,
)
from campus_job_desk.domain.enums import (
    Eligibility,
    EvidenceFit,
    OpportunityKind,
    ProfileFactKind,
    Trust,
    VerificationResult,
)
from campus_job_desk.domain.profile import EvidenceProfile

EDUCATION_RANK = {"\u5927\u4e13": 1, "\u672c\u79d1": 2, "\u7855\u58eb": 3, "\u535a\u58eb": 4}
FIT_CAPABILITIES = {
    "AI": ("AI", "\u4eba\u5de5\u667a\u80fd", "\u5927\u6a21\u578b", "LLM", "RAG", "Agent", "\u673a\u5668\u5b66\u4e60"),
    "\u4ea7\u54c1": ("\u4ea7\u54c1", "\u9700\u6c42\u5206\u6790", "\u7528\u6237\u8c03\u7814", "PRD", "\u539f\u578b", "\u7ade\u54c1"),
    "\u6570\u636e": ("\u6570\u636e", "SQL", "Python", "\u6307\u6807", "\u5206\u6790"),
    "\u5e73\u53f0": ("\u5e73\u53f0", "\u4e2d\u53f0", "\u5f00\u53d1\u8005\u670d\u52a1"),
    "\u89e3\u51b3\u65b9\u6848": ("\u89e3\u51b3\u65b9\u6848", "\u54a8\u8be2", "\u4ea4\u4ed8", "\u5b9e\u65bd"),
    "\u4eff\u771f": ("\u4eff\u771f", "\u6570\u5b57\u5b6a\u751f", "SIL", "HIL"),
    "\u6d4b\u8bd5\u8bc4\u6d4b": ("\u6d4b\u8bd5", "\u8bc4\u6d4b", "\u8bc4\u4f30", "\u8d28\u91cf"),
}


class DecisionService:
    def evaluate(
        self,
        context: JobDecisionContext,
        profile: EvidenceProfile,
        *,
        as_of: datetime | None = None,
        stale_after_days: int = 14,
    ) -> DecisionBundle:
        generated_at = as_of or datetime.now(timezone.utc)
        return DecisionBundle(
            generated_at=generated_at,
            eligibility=self.evaluate_eligibility(context, profile),
            evidence_fit=self.evaluate_evidence_fit(context, profile),
            trust=self.evaluate_trust(
                context,
                as_of=generated_at,
                stale_after_days=stale_after_days,
            ),
        )

    def evaluate_eligibility(
        self,
        context: JobDecisionContext,
        profile: EvidenceProfile,
    ) -> EligibilityDecision:
        if context.opportunity_kind is OpportunityKind.CAMPAIGN:
            return EligibilityDecision(
                result=Eligibility.UNKNOWN,
                reasons=[
                    DecisionReason(
                        code="campaign_not_posting",
                        field="opportunity_kind",
                        message="\u62db\u8058\u9879\u76ee\u4e0d\u662f\u53ef\u5355\u72ec\u6295\u9012\u7684\u5177\u4f53\u5c97\u4f4d",
                    )
                ],
                unknowns=[
                    DecisionUnknown(
                        code="posting_required",
                        field="posting",
                        message="\u9700\u5148\u5173\u8054\u6216\u521b\u5efa\u5b98\u65b9\u5177\u4f53\u5c97\u4f4d",
                    )
                ],
            )

        reasons: list[DecisionReason] = []
        unknowns: list[DecisionUnknown] = []
        failures: list[str] = []

        self._evaluate_status(context, reasons, unknowns, failures)
        self._evaluate_city(context, profile, reasons, unknowns, failures)
        self._evaluate_graduation(context, profile, reasons, unknowns, failures)
        self._evaluate_education(context, profile, reasons, unknowns, failures)
        self._evaluate_recruitment_type(context, profile, reasons, unknowns, failures)

        if failures:
            result = Eligibility.FAIL
        elif unknowns:
            result = Eligibility.UNKNOWN
        else:
            result = Eligibility.PASS
        return EligibilityDecision(result=result, reasons=reasons, unknowns=unknowns)

    def evaluate_evidence_fit(
        self,
        context: JobDecisionContext,
        profile: EvidenceProfile,
    ) -> EvidenceFitDecision:
        target_text = f"{context.record.title}\n{context.jd_text}".strip()
        target_capabilities = self._capabilities_in(target_text)
        if not target_capabilities:
            return EvidenceFitDecision(
                result=EvidenceFit.UNKNOWN,
                unknowns=[
                    DecisionUnknown(
                        code="no_target_capabilities",
                        field="jd_text",
                        message="\u5c97\u4f4d\u6807\u9898\u548c JD \u4e2d\u7f3a\u5c11\u53ef\u7528\u900f\u660e\u8bcd\u5178\u8bc4\u4f30\u7684\u80fd\u529b\u8981\u6c42",
                    )
                ],
            )

        confirmed = [
            fact
            for fact in profile.confirmed_facts()
            if fact.kind
            in {
                ProfileFactKind.SKILL,
                ProfileFactKind.EXPERIENCE,
                ProfileFactKind.PROJECT,
            }
        ]
        if not confirmed:
            return EvidenceFitDecision(
                result=EvidenceFit.UNKNOWN,
                unknowns=[
                    DecisionUnknown(
                        code="no_confirmed_profile_facts",
                        field="profile.facts",
                        message="\u6ca1\u6709\u7ecf\u7528\u6237\u786e\u8ba4\u7684\u7b80\u5386\u4e8b\u5b9e\uff0c\u4e0d\u80fd\u5224\u5b9a\u7ecf\u5386\u5339\u914d",
                    )
                ],
            )

        matched: dict[str, list[str]] = {}
        for capability in target_capabilities:
            references = []
            terms = FIT_CAPABILITIES[capability]
            for fact in confirmed:
                fact_text = f"{fact.value} {fact.evidence_text}"
                if any(self._contains_term(fact_text, term) for term in terms):
                    references.append(fact.fact_id)
            if references:
                matched[capability] = sorted(set(references))

        if not matched:
            return EvidenceFitDecision(
                result=EvidenceFit.LOW,
                reasons=[
                    DecisionReason(
                        code="no_supported_capability_match",
                        field="profile.facts",
                        message="\u5df2\u786e\u8ba4\u7b80\u5386\u4e8b\u5b9e\u672a\u8986\u76d6\u5c97\u4f4d\u80fd\u529b\u8bcd\uff1a"
                        + "\u3001".join(sorted(target_capabilities)),
                    )
                ],
            )

        reasons = [
            DecisionReason(
                code="supported_capability_match",
                field="profile.facts",
                message=f"\u7b80\u5386\u8bc1\u636e\u652f\u6301\u80fd\u529b\uff1a{capability}",
                evidence_refs=references,
            )
            for capability, references in sorted(matched.items())
        ]
        coverage = len(matched) / len(target_capabilities)
        facts_by_id = {fact.fact_id: fact for fact in confirmed}
        evidence_spans = {
            (facts_by_id[ref].span.start, facts_by_id[ref].span.end)
            for refs in matched.values()
            for ref in refs
        }
        evidence_count = len(evidence_spans)
        if len(matched) >= 3 and coverage >= 0.6 and evidence_count >= 2:
            result = EvidenceFit.PRIMARY
        elif len(matched) >= 2 or coverage >= 0.5:
            result = EvidenceFit.APPLY
        else:
            result = EvidenceFit.STRETCH
        return EvidenceFitDecision(result=result, reasons=reasons)

    def evaluate_trust(
        self,
        context: JobDecisionContext,
        *,
        as_of: datetime | None = None,
        stale_after_days: int = 14,
    ) -> TrustDecision:
        now = as_of or datetime.now(timezone.utc)
        if context.verification_result in {
            VerificationResult.NOT_FOUND,
            VerificationResult.BLOCKED,
        }:
            code = f"official_{context.verification_result.value.lower()}"
            return TrustDecision(
                result=Trust.UNKNOWN,
                reasons=[
                    DecisionReason(
                        code=code,
                        field="verification_result",
                        message="\u5b98\u65b9\u6838\u9a8c\u672a\u8bc1\u660e\u5c97\u4f4d\u5173\u95ed\uff0c\u4e0d\u5c06\u8be5\u72b6\u6001\u89e3\u91ca\u4e3a CLOSED",
                    )
                ],
                unknowns=[
                    DecisionUnknown(
                        code="official_status_unresolved",
                        field="status",
                        message="\u5177\u4f53\u5c97\u4f4d\u5b98\u65b9\u72b6\u6001\u4ecd\u5f85\u786e\u8ba4",
                    )
                ],
            )

        freshest = context.official_checked_at or context.latest_source_at
        if freshest and self._is_older_than(
            now,
            freshest,
            days=stale_after_days,
        ):
            return TrustDecision(
                result=Trust.STALE,
                reasons=[
                    DecisionReason(
                        code="evidence_stale",
                        field="official_checked_at",
                        message=f"\u6700\u65b0\u8bc1\u636e\u8d85\u8fc7 {stale_after_days} \u5929\u672a\u6838\u9a8c",
                    )
                ],
            )

        if context.official_specific_posting and context.verification_result in {
            VerificationResult.OPEN,
            VerificationResult.CLOSED,
        }:
            if context.conflicting_fields:
                return TrustDecision(
                    result=Trust.VERIFIED_WITH_CONFLICT,
                    reasons=[
                        DecisionReason(
                            code="official_posting_with_conflicts",
                            field="conflicting_fields",
                            message="\u5177\u4f53\u5b98\u65b9\u5c97\u4f4d\u5df2\u6838\u9a8c\uff0c\u4f46\u805a\u5408\u6765\u6e90\u5b58\u5728\u51b2\u7a81\uff1a"
                            + "\u3001".join(context.conflicting_fields),
                        )
                    ],
                )
            return TrustDecision(
                result=Trust.VERIFIED,
                reasons=[
                    DecisionReason(
                        code="official_specific_posting_verified",
                        field="verification_result",
                        message="\u5177\u4f53\u5b98\u65b9\u5c97\u4f4d\u72b6\u6001\u5df2\u6838\u9a8c",
                    )
                ],
            )

        if context.conflicting_fields:
            return TrustDecision(
                result=Trust.CONFLICTED,
                reasons=[
                    DecisionReason(
                        code="unresolved_source_conflicts",
                        field="conflicting_fields",
                        message="\u5b58\u5728\u672a\u7ecf\u5b98\u65b9\u5177\u4f53\u5c97\u4f4d\u6d88\u89e3\u7684\u5b57\u6bb5\u51b2\u7a81\uff1a"
                        + "\u3001".join(context.conflicting_fields),
                    )
                ],
            )

        if context.source_count >= 2:
            return TrustDecision(
                result=Trust.CONSISTENT,
                reasons=[
                    DecisionReason(
                        code="multiple_sources_consistent",
                        field="source_count",
                        message=f"{context.source_count} \u4e2a\u6765\u6e90\u65e0\u5df2\u77e5\u51b2\u7a81\uff0c\u4f46\u5c1a\u672a\u6838\u9a8c\u5177\u4f53\u5b98\u65b9\u5c97\u4f4d",
                    )
                ],
                unknowns=[
                    DecisionUnknown(
                        code="official_posting_not_verified",
                        field="official_specific_posting",
                        message="\u7f3a\u5c11\u5177\u4f53\u5b98\u65b9\u5c97\u4f4d\u8bc1\u636e",
                    )
                ],
            )

        return TrustDecision(
            result=Trust.UNKNOWN,
            unknowns=[
                DecisionUnknown(
                    code="insufficient_source_evidence",
                    field="source_count",
                    message="\u53ea\u6709\u5355\u4e00\u6216\u65e0\u53ef\u7528\u6765\u6e90\uff0c\u4e14\u672a\u6838\u9a8c\u5177\u4f53\u5b98\u65b9\u5c97\u4f4d",
                )
            ],
        )

    @staticmethod
    def _evaluate_status(
        context: JobDecisionContext,
        reasons: list[DecisionReason],
        unknowns: list[DecisionUnknown],
        failures: list[str],
    ) -> None:
        if context.verification_result is VerificationResult.CLOSED:
            failures.append("status")
            reasons.append(
                DecisionReason(
                    code="officially_closed",
                    field="status",
                    message="\u5b98\u65b9\u6838\u9a8c\u7ed3\u679c\u4e3a\u5df2\u5173\u95ed",
                )
            )
        elif context.verification_result is VerificationResult.OPEN:
            reasons.append(
                DecisionReason(
                    code="officially_open",
                    field="status",
                    message="\u5b98\u65b9\u6838\u9a8c\u7ed3\u679c\u4e3a\u5f00\u653e",
                )
            )
        else:
            unknowns.append(
                DecisionUnknown(
                    code="status_not_confirmed",
                    field="status",
                    message="\u5c97\u4f4d\u5f00\u653e\u72b6\u6001\u5c1a\u672a\u5b98\u65b9\u786e\u8ba4",
                )
            )

    @staticmethod
    def _evaluate_city(
        context: JobDecisionContext,
        profile: EvidenceProfile,
        reasons: list[DecisionReason],
        unknowns: list[DecisionUnknown],
        failures: list[str],
    ) -> None:
        accepted = {item.strip() for item in profile.preferences.accepted_cities if item.strip()}
        cities = {item.strip() for item in context.record.cities if item.strip()}
        if not accepted:
            unknowns.append(
                DecisionUnknown(
                    code="accepted_cities_missing",
                    field="preferences.accepted_cities",
                    message="\u7528\u6237\u5c1a\u672a\u786e\u8ba4\u53ef\u63a5\u53d7\u57ce\u5e02",
                )
            )
        elif not cities:
            unknowns.append(
                DecisionUnknown(
                    code="posting_city_missing",
                    field="cities",
                    message="\u5177\u4f53\u5c97\u4f4d\u57ce\u5e02\u7f3a\u5931",
                )
            )
        elif "\u5168\u56fd" in cities or accepted & cities:
            reasons.append(
                DecisionReason(
                    code="city_accepted",
                    field="cities",
                    message="\u5177\u4f53\u5c97\u4f4d\u57ce\u5e02\u5728\u7528\u6237\u53ef\u63a5\u53d7\u8303\u56f4\u5185",
                )
            )
        else:
            failures.append("cities")
            reasons.append(
                DecisionReason(
                    code="city_not_accepted",
                    field="cities",
                    message="\u5177\u4f53\u5c97\u4f4d\u57ce\u5e02\u4e0d\u5728\u7528\u6237\u53ef\u63a5\u53d7\u8303\u56f4\u5185",
                )
            )

    @staticmethod
    def _evaluate_graduation(
        context: JobDecisionContext,
        profile: EvidenceProfile,
        reasons: list[DecisionReason],
        unknowns: list[DecisionUnknown],
        failures: list[str],
    ) -> None:
        candidate_years = {
            re.search(r"(?:19|20)\d{2}", fact.value).group(0)
            for fact in profile.confirmed_facts(ProfileFactKind.GRADUATION_YEAR)
            if re.search(r"(?:19|20)\d{2}", fact.value)
        }
        posting_years = {
            re.search(r"(?:19|20)\d{2}", value).group(0)
            for value in context.record.graduation_years
            if re.search(r"(?:19|20)\d{2}", value)
        }
        if not candidate_years:
            unknowns.append(
                DecisionUnknown(
                    code="candidate_graduation_unconfirmed",
                    field="profile.facts.graduation_year",
                    message="\u7b80\u5386\u4e2d\u6ca1\u6709\u7ecf\u7528\u6237\u786e\u8ba4\u7684\u6bd5\u4e1a\u5c4a\u6b21",
                )
            )
        elif not posting_years:
            unknowns.append(
                DecisionUnknown(
                    code="posting_graduation_missing",
                    field="graduation_years",
                    message="\u5177\u4f53\u5c97\u4f4d\u672a\u660e\u786e\u62db\u8058\u5c4a\u6b21",
                )
            )
        elif candidate_years & posting_years:
            fact_refs = [
                fact.fact_id
                for fact in profile.confirmed_facts(ProfileFactKind.GRADUATION_YEAR)
            ]
            reasons.append(
                DecisionReason(
                    code="graduation_year_matches",
                    field="graduation_years",
                    message="\u6bd5\u4e1a\u5c4a\u6b21\u7b26\u5408\u5c97\u4f4d\u8981\u6c42",
                    evidence_refs=fact_refs,
                )
            )
        else:
            failures.append("graduation_years")
            reasons.append(
                DecisionReason(
                    code="graduation_year_mismatch",
                    field="graduation_years",
                    message="\u6bd5\u4e1a\u5c4a\u6b21\u4e0d\u7b26\u5408\u5c97\u4f4d\u8981\u6c42",
                )
            )

    @staticmethod
    def _evaluate_education(
        context: JobDecisionContext,
        profile: EvidenceProfile,
        reasons: list[DecisionReason],
        unknowns: list[DecisionUnknown],
        failures: list[str],
    ) -> None:
        education_facts = profile.confirmed_facts(ProfileFactKind.EDUCATION)
        candidate_ranks = [EDUCATION_RANK[fact.value] for fact in education_facts if fact.value in EDUCATION_RANK]
        required_ranks = [
            rank
            for value in context.record.education
            for name, rank in EDUCATION_RANK.items()
            if name in value
        ]
        if not candidate_ranks:
            unknowns.append(
                DecisionUnknown(
                    code="candidate_education_unconfirmed",
                    field="profile.facts.education",
                    message="\u7b80\u5386\u4e2d\u6ca1\u6709\u7ecf\u7528\u6237\u786e\u8ba4\u7684\u5b66\u5386\u4e8b\u5b9e",
                )
            )
        elif not required_ranks:
            unknowns.append(
                DecisionUnknown(
                    code="posting_education_missing",
                    field="education",
                    message="\u5177\u4f53\u5c97\u4f4d\u672a\u660e\u786e\u5b66\u5386\u8981\u6c42",
                )
            )
        elif max(candidate_ranks) >= min(required_ranks):
            reasons.append(
                DecisionReason(
                    code="education_meets_minimum",
                    field="education",
                    message="\u5df2\u786e\u8ba4\u5b66\u5386\u8fbe\u5230\u5c97\u4f4d\u6700\u4f4e\u8981\u6c42",
                    evidence_refs=[fact.fact_id for fact in education_facts],
                )
            )
        else:
            failures.append("education")
            reasons.append(
                DecisionReason(
                    code="education_below_minimum",
                    field="education",
                    message="\u5df2\u786e\u8ba4\u5b66\u5386\u4f4e\u4e8e\u5c97\u4f4d\u6700\u4f4e\u8981\u6c42",
                )
            )

    @staticmethod
    def _evaluate_recruitment_type(
        context: JobDecisionContext,
        profile: EvidenceProfile,
        reasons: list[DecisionReason],
        unknowns: list[DecisionUnknown],
        failures: list[str],
    ) -> None:
        accepted = {
            DecisionService._normalize_recruitment_type(value)
            for value in profile.preferences.accepted_recruitment_types
            if value.strip()
        }
        posting = DecisionService._normalize_recruitment_type(context.record.recruitment_type)
        if not accepted:
            unknowns.append(
                DecisionUnknown(
                    code="accepted_recruitment_types_missing",
                    field="preferences.accepted_recruitment_types",
                    message="\u7528\u6237\u5c1a\u672a\u786e\u8ba4\u53ef\u63a5\u53d7\u62db\u8058\u7c7b\u578b",
                )
            )
        elif not posting:
            unknowns.append(
                DecisionUnknown(
                    code="posting_recruitment_type_missing",
                    field="recruitment_type",
                    message="\u5177\u4f53\u5c97\u4f4d\u62db\u8058\u7c7b\u578b\u7f3a\u5931",
                )
            )
        elif posting in accepted:
            reasons.append(
                DecisionReason(
                    code="recruitment_type_accepted",
                    field="recruitment_type",
                    message="\u62db\u8058\u7c7b\u578b\u5728\u7528\u6237\u53ef\u63a5\u53d7\u8303\u56f4\u5185",
                )
            )
        else:
            failures.append("recruitment_type")
            reasons.append(
                DecisionReason(
                    code="recruitment_type_not_accepted",
                    field="recruitment_type",
                    message="\u62db\u8058\u7c7b\u578b\u4e0d\u5728\u7528\u6237\u53ef\u63a5\u53d7\u8303\u56f4\u5185",
                )
            )

    @staticmethod
    def _normalize_recruitment_type(value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            return ""
        if "\u8865\u5f55" in normalized:
            return "\u8865\u5f55"
        if "\u5b9e\u4e60" in normalized:
            return "\u5b9e\u4e60"
        if any(marker in normalized for marker in ("\u79cb\u62db", "\u6625\u62db", "\u6821\u62db", "\u5e94\u5c4a", "\u63d0\u524d\u6279")):
            return "\u6821\u62db"
        return normalized

    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        if term.isascii() and term.isalnum():
            return (
                re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])",
                    text,
                    re.IGNORECASE,
                )
                is not None
            )
        return term.lower() in text.lower()

    @classmethod
    def _capabilities_in(cls, text: str) -> set[str]:
        return {
            capability
            for capability, terms in FIT_CAPABILITIES.items()
            if any(cls._contains_term(text, term) for term in terms)
        }

    @staticmethod
    def _is_older_than(now: datetime, then: datetime, *, days: int) -> bool:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return then < now - timedelta(days=days)
