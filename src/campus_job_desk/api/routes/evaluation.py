from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])
REPORT_PATH = Path(__file__).resolve().parents[4] / "evaluation" / "results" / "latest.json"
REPORT_HTML_PATH = Path(__file__).resolve().parents[4] / "docs" / "evaluation" / "report.html"


@router.get("/summary")
def evaluation_summary() -> dict[str, Any]:
    """Expose only the aggregate, public-safe evaluation result."""

    if not REPORT_PATH.is_file():
        raise HTTPException(status_code=503, detail="评测报告尚未生成，请先运行 make evaluate")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return {
        "schema_version": report["schema_version"],
        "harness_version": report["harness_version"],
        "generated_at": report["generated_at"],
        "methodology": report["methodology"],
        "fixture_summary": report["fixture_summary"],
        "database_quality": report["database_quality"],
        "api_performance": report["api_performance"],
        "limitations": report["limitations"],
    }


@router.get("/report", response_class=FileResponse)
def evaluation_report() -> FileResponse:
    """Serve the generated, self-contained public evaluation report."""

    if not REPORT_HTML_PATH.is_file():
        raise HTTPException(status_code=503, detail="HTML 评测报告尚未生成")
    return FileResponse(
        REPORT_HTML_PATH,
        media_type="text/html; charset=utf-8",
        filename="campus-job-desk-evaluation.html",
        content_disposition_type="inline",
    )
