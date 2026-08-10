from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web" / "public" / "demo-data.json"
STATIC_EXPORTS = {
    "csv": ROOT / "web" / "public" / "demo-shortlist.csv",
    "json": ROOT / "web" / "public" / "demo-shortlist.json",
    "markdown": ROOT / "web" / "public" / "demo-shortlist.md",
}


def get(client: TestClient, path: str):  # type: ignore[no-untyped-def]
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def main() -> None:
    os.environ.setdefault("CJD_ENVIRONMENT", "public-demo")
    os.environ.setdefault("CJD_DATABASE_URL", "sqlite:///data/demo/public-demo.sqlite")
    from campus_job_desk.api.app import app

    with TestClient(app) as client:
        opportunities_page = get(client, "/api/opportunities?page=1&page_size=100")
        opportunities = opportunities_page["items"]
        details = {
            item["id"]: get(client, f"/api/opportunities/{item['id']}")
            for item in opportunities
        }
        meta = get(client, "/api/meta")
        meta.update(
            {
                "environment": "static-demo",
                "read_only": True,
                "data_mode": "synthetic-demo",
                "label": "在线合成演示",
            }
        )
        evaluation = get(client, "/api/evaluation/summary")
        bundle = {
            "schema_version": "static-demo.v1",
            "generated_at": evaluation["generated_at"],
            "meta": meta,
            "dashboard": get(client, "/api/workspace/dashboard"),
            "opportunities": opportunities,
            "ready_queue": get(
                client,
                "/api/workspace/decision-queue?queue=ready&page=1&page_size=100",
            )["items"],
            "verify_first_queue": get(
                client,
                "/api/workspace/decision-queue?queue=verify_first&page=1&page_size=100",
            )["items"],
            "details": details,
            "profile": get(client, "/api/workspace/profile"),
            "shortlist": get(client, "/api/workspace/shortlist"),
            "sources": get(client, "/api/sources"),
            "batches": get(client, "/api/sources/batches"),
            "connectors": get(client, "/api/sources/connectors"),
            "sync_runs": get(client, "/api/sources/sync-runs"),
            "duplicates": get(
                client,
                "/api/opportunities/review/duplicates?decision=REVIEW&limit=50",
            ),
            "evaluation": evaluation,
        }
        for export_format, export_path in STATIC_EXPORTS.items():
            response = client.get(
                f"/api/workspace/shortlist/export?format={export_format}"
            )
            response.raise_for_status()
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_bytes(response.content)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT.relative_to(ROOT)),
                "opportunities": len(opportunities),
                "details": len(details),
                "shortlist_exports": len(STATIC_EXPORTS),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
