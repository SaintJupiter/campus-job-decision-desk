from __future__ import annotations

import json
from time import perf_counter

from fastapi.testclient import TestClient

from campus_job_desk.api.app import app


def timed(client: TestClient, path: str) -> tuple[float, int, object]:
    started = perf_counter()
    response = client.get(path)
    elapsed_ms = (perf_counter() - started) * 1000
    return elapsed_ms, response.status_code, response.json()


def main() -> None:
    with TestClient(app) as client:
        list_ms, list_status, payload = timed(
            client,
            "/api/opportunities?page=1&page_size=30&kind=POSTING",
        )
        items = payload.get("items", []) if isinstance(payload, dict) else []
        detail_ms = 0.0
        detail_status = 0
        if items:
            detail_ms, detail_status, _ = timed(
                client,
                f"/api/opportunities/{items[0]['id']}",
            )
        print(
            json.dumps(
                {
                    "list_ms": round(list_ms, 2),
                    "list_status": list_status,
                    "list_count": len(items),
                    "detail_ms": round(detail_ms, 2),
                    "detail_status": detail_status,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
