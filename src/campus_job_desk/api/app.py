from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from campus_job_desk.api.routes.evaluation import router as evaluation_router
from campus_job_desk.api.routes.opportunities import router as opportunities_router
from campus_job_desk.api.routes.sources import router as sources_router
from campus_job_desk.api.routes.workspace import router as workspace_router
from campus_job_desk.database import ENGINE, SessionLocal, create_schema
from campus_job_desk.domain.enums import (
    ApplicationStage,
    DuplicateDecision,
    Eligibility,
    EvidenceFit,
    OpportunityKind,
    ProfileFactKind,
    ReviewDecision,
    SourceKind,
    Trust,
    VerificationResult,
)
from campus_job_desk.services.privacy import (
    validate_public_demo_database,
    validate_public_demo_database_path,
)
from campus_job_desk.settings import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
    if settings.environment == "public-demo":
        # Fail before migrations or reconciliation can touch a mistakenly
        # configured private workspace.
        validate_public_demo_database_path(settings.database_url)
        with SessionLocal() as session:
            validate_public_demo_database(session, settings.database_url)
    else:
        create_schema(ENGINE)
        from campus_job_desk.services.workflow import reconcile_stale_current_decisions

        with SessionLocal() as session:
            if reconcile_stale_current_decisions(session):
                session.commit()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="多源岗位核验与投递决策 API",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect_public_demo_writes(request: Request, call_next):  # type: ignore[no-untyped-def]
    if settings.environment == "public-demo" and request.method not in {"GET", "HEAD", "OPTIONS"}:
        return JSONResponse(
            status_code=403,
            content={"detail": "公开演示为只读合成数据；完整交互请在本地运行。"},
        )
    return await call_next(request)
app.include_router(sources_router)
app.include_router(opportunities_router)
app.include_router(workspace_router)
app.include_router(evaluation_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "campus-job-desk", "version": app.version}


@app.get("/api/meta")
def runtime_metadata() -> dict[str, object]:
    read_only = settings.environment == "public-demo"
    return {
        "environment": settings.environment,
        "read_only": read_only,
        "data_mode": "synthetic-demo" if read_only else "local-workspace",
        "label": "只读合成演示" if read_only else "本地证据工作区",
    }


@app.get("/api/meta/enums")
def enum_metadata() -> dict[str, list[str]]:
    return {
        "opportunity_kind": [item.value for item in OpportunityKind],
        "verification_result": [item.value for item in VerificationResult],
        "eligibility": [item.value for item in Eligibility],
        "evidence_fit": [item.value for item in EvidenceFit],
        "trust": [item.value for item in Trust],
        "review_decision": [item.value for item in ReviewDecision],
        "application_stage": [item.value for item in ApplicationStage],
        "duplicate_decision": [item.value for item in DuplicateDecision],
        "source_kind": [item.value for item in SourceKind],
        "profile_fact_kind": [item.value for item in ProfileFactKind],
    }


dist = Path(__file__).resolve().parents[3] / "dist"
if dist.exists():
    resolved_dist = dist.resolve()
    assets = dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def serve_spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        candidate = (resolved_dist / path).resolve()
        try:
            candidate.relative_to(resolved_dist)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="静态资源不存在") from exc
        if path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(resolved_dist / "index.html")
