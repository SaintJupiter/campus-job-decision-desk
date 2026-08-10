from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from campus_job_desk.api.app import app


def _request_json(client: TestClient, method: str, url: str, **kwargs: Any) -> Any:
    response = client.request(method, url, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在指定本地数据库上复跑画像、筛选、三轴和短名单门禁"
    )
    parser.add_argument("--resume", type=Path, required=True)
    parser.add_argument("--city", default="上海")
    parser.add_argument("--graduation-year", default="2027")
    parser.add_argument("--recruitment-type", default="秋招")
    parser.add_argument(
        "--accepted-recruitment-types",
        nargs="+",
        default=["秋招", "实习"],
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=["AI产品", "产品", "数据产品", "解决方案"],
    )
    parser.add_argument("--candidate-limit", type=int, default=30)
    args = parser.parse_args()

    if not args.resume.is_file():
        raise SystemExit(f"简历文件不存在：{args.resume}")

    with TestClient(app) as client:
        with args.resume.open("rb") as handle:
            _request_json(
                client,
                "POST",
                "/api/workspace/profile/upload",
                files={"file": (args.resume.name, handle, "application/pdf")},
            )

        profile = _request_json(client, "GET", "/api/workspace/profile")
        for fact in profile["facts"]:
            if not fact["confirmed"]:
                _request_json(
                    client,
                    "PATCH",
                    f"/api/workspace/profile/facts/{fact['id']}",
                    json={"confirmed": True},
                )

        for key, value in (
            ("accepted_cities", [args.city]),
            ("accepted_recruitment_types", args.accepted_recruitment_types),
            ("target_role_keywords", args.keywords),
        ):
            _request_json(
                client,
                "PUT",
                f"/api/workspace/profile/preferences/{key}",
                json={
                    "key": key,
                    "value": value,
                    "hard_constraint": key
                    in {"accepted_cities", "accepted_recruitment_types"},
                    "confirmed": True,
                },
            )

        candidate_by_id: dict[str, dict[str, Any]] = {}
        query_totals: dict[str, int] = {}
        for keyword in args.keywords:
            payload = _request_json(
                client,
                "GET",
                "/api/opportunities",
                params={
                    "city": args.city,
                    "graduation_year": args.graduation_year,
                    "recruitment_type": args.recruitment_type,
                    "search": keyword,
                    "kind": "POSTING",
                    "page_size": 100,
                },
            )
            query_totals[keyword] = payload["total"]
            for item in payload["items"]:
                candidate_by_id.setdefault(item["id"], item)

        candidates = sorted(
            candidate_by_id.values(),
            key=lambda item: (
                item["official_job_id"] is None,
                not bool(item["apply_url"]),
                item["company"],
                item["title"],
            ),
        )[: args.candidate_limit]
        candidate_ids = [item["id"] for item in candidates]
        recomputed = _request_json(
            client,
            "POST",
            "/api/workspace/decisions/recompute",
            json={"opportunity_ids": candidate_ids},
        )

        decision_items: list[dict[str, Any]] = []
        for candidate in candidates:
            detail = _request_json(
                client, "GET", f"/api/opportunities/{candidate['id']}"
            )
            item = detail["item"]
            current = next(
                (
                    decision
                    for decision in detail["decision_history"]
                    if decision["is_current"]
                ),
                None,
            )
            decision_items.append(
                {
                    "id": item["id"],
                    "company": item["company"],
                    "title": item["title"],
                    "official_job_id": item["official_job_id"],
                    "apply_url": item["apply_url"],
                    "eligibility": current["eligibility"] if current else None,
                    "evidence_fit": current["evidence_fit"] if current else None,
                    "trust": current["trust"] if current else None,
                    "unknown_count": len(current["unknowns"]) if current else None,
                }
            )

        shortlist_gate: dict[str, Any] = {"tested": False}
        if decision_items:
            target = decision_items[0]
            response = client.post(
                f"/api/workspace/shortlist/{target['id']}",
                json={"priority": 1, "note": "真实链路验收"},
            )
            shortlist_gate = {
                "tested": True,
                "opportunity_id": target["id"],
                "status_code": response.status_code,
                "accepted": response.status_code == 201,
                "detail": response.json().get("detail")
                if response.headers.get("content-type", "").startswith("application/json")
                else response.text,
            }

        dashboard = _request_json(client, "GET", "/api/workspace/dashboard")
        verify_first = _request_json(
            client,
            "GET",
            "/api/workspace/decision-queue",
            params={"queue": "verify_first", "page_size": 5},
        )
        confirmed_profile = _request_json(client, "GET", "/api/workspace/profile")

    report = {
        "profile": {
            "uploaded_file": args.resume.name,
            "extracted_fact_count": len(profile["facts"]),
            "confirmed_fact_count": sum(
                1 for fact in confirmed_profile["facts"] if fact["confirmed"]
            ),
            "preference_count": len(confirmed_profile["preferences"]),
        },
        "search_scope": {
            "city": args.city,
            "graduation_year": args.graduation_year,
            "recruitment_type": args.recruitment_type,
            "query_totals": query_totals,
            "unique_candidate_count": len(candidate_by_id),
            "evaluated_candidate_count": len(candidates),
        },
        "recompute": recomputed,
        "decision_sample": decision_items[:10],
        "shortlist_gate": shortlist_gate,
        "dashboard": dashboard,
        "verify_first_total": verify_first["total"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
