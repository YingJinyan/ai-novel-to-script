"""HTTP routes for the screenplay backend."""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.models import (
    AIGenerationRequest,
    ChapterParseResponse,
    ErrorResponse,
    HealthResponse,
    LocalGenerationRequest,
    LocalGenerationResponse,
    NovelTextRequest,
    ParsedChapter,
    ProviderStatusResponse,
    ProviderModelsResponse,
    QualityGateErrorResponse,
    ValidationIssue,
    ValidationReport,
    ValidationRequest,
)
from backend.pipeline import analyze_chapters, generate_local_screenplay, generate_qiniu_screenplay
from backend.providers import QiniuAIError, QiniuClient, QiniuSettings
from scripts.validate_example import EXAMPLE_PATH, validate_screenplay


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="ai-novel-to-script-api",
        version="0.1.0",
    )


@router.get("/example", response_model=dict[str, Any])
def get_example() -> dict[str, Any]:
    """Return the repository's example YAML as JSON."""
    try:
        example = yaml.safe_load(EXAMPLE_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=500, detail="Failed to load example screenplay.") from exc

    if not isinstance(example, dict):
        raise HTTPException(status_code=500, detail="Example screenplay must be a YAML object.")
    return example


@router.get("/providers/qiniu/status", response_model=ProviderStatusResponse)
def qiniu_provider_status() -> ProviderStatusResponse:
    """Return non-secret provider configuration status."""
    settings = QiniuSettings.from_env()
    return ProviderStatusResponse(
        provider="qiniu-ai",
        credentials_configured=settings.credentials_configured,
        configured=settings.configured,
        model=settings.model,
        base_url=settings.base_url,
        mode="qiniu_ai",
    )


@router.get(
    "/providers/qiniu/models",
    response_model=ProviderModelsResponse,
    responses={
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def qiniu_provider_models() -> ProviderModelsResponse | JSONResponse:
    """Return model IDs from Qiniu without exposing the API key."""
    settings = QiniuSettings.from_env()
    try:
        models = QiniuClient(settings).list_models()
    except QiniuAIError as exc:
        status_code = 503 if exc.code == "qiniu_provider_not_configured" else 502
        error = ErrorResponse(code=exc.code, message=str(exc), related_ids=[])
        return JSONResponse(status_code=status_code, content=error.model_dump())
    return ProviderModelsResponse(
        provider="qiniu-ai",
        selected_model=settings.model,
        models=models,
    )


@router.post("/validate", response_model=ValidationReport)
def validate(request: ValidationRequest) -> dict:
    """Validate a screenplay and return its structured quality report."""
    return validate_screenplay(request.screenplay, request.source_texts)


@router.post(
    "/projects/parse",
    response_model=ChapterParseResponse,
    responses={422: {"model": ErrorResponse}},
)
def parse_project(request: NovelTextRequest) -> ChapterParseResponse:
    """Parse chapters while preserving partial results for author review."""
    result = analyze_chapters(request.novel_text)
    return ChapterParseResponse(
        eligible=result.eligible,
        chapters=[
            ParsedChapter(
                id=chapter.id,
                order=chapter.order,
                title=chapter.title,
                text=chapter.text,
            )
            for chapter in result.chapters
        ],
        preamble=result.preamble,
        total_characters=result.total_characters,
        issues=[ValidationIssue.model_validate(issue) for issue in result.issues],
    )


@router.post(
    "/projects/generate-local",
    response_model=LocalGenerationResponse,
    responses={
        422: {"model": ErrorResponse},
        500: {"model": QualityGateErrorResponse},
    },
)
def generate_project_local(
    request: LocalGenerationRequest,
) -> LocalGenerationResponse | JSONResponse:
    """Generate a deterministic screenplay or return the first blocking input issue."""
    parse_result = analyze_chapters(request.novel_text)
    if not parse_result.eligible:
        issue = next(
            issue for issue in parse_result.issues if issue["severity"] == "error"
        )
        error = ErrorResponse(
            code=issue["code"],
            message=issue["message"],
            related_ids=issue["related_ids"],
        )
        return JSONResponse(status_code=422, content=error.model_dump())

    result = generate_local_screenplay(request.novel_text, title=request.title)
    quality_report = ValidationReport.model_validate(
        validate_screenplay(result.screenplay, result.source_texts)
    )
    if not quality_report.passed:
        error = QualityGateErrorResponse(
            code="generated_screenplay_failed_quality_gate",
            message="生成结果未通过质量门禁。",
            related_ids=[],
            quality_report=quality_report,
        )
        return JSONResponse(status_code=500, content=error.model_dump())
    return LocalGenerationResponse(
        screenplay=result.screenplay,
        source_texts=result.source_texts,
        issues=[ValidationIssue.model_validate(issue) for issue in result.issues],
        quality_report=quality_report,
    )


@router.post(
    "/projects/generate-ai",
    response_model=LocalGenerationResponse,
    responses={
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        500: {"model": QualityGateErrorResponse},
    },
)
def generate_project_ai(
    request: AIGenerationRequest,
) -> LocalGenerationResponse | JSONResponse:
    """Generate with Qiniu AI inside a deterministic, quality-gated source skeleton."""
    parse_result = analyze_chapters(request.novel_text)
    if not parse_result.eligible:
        issue = next(
            issue for issue in parse_result.issues if issue["severity"] == "error"
        )
        error = ErrorResponse(
            code=issue["code"],
            message=issue["message"],
            related_ids=issue["related_ids"],
        )
        return JSONResponse(status_code=422, content=error.model_dump())

    try:
        result = generate_qiniu_screenplay(
            request.novel_text,
            title=request.title,
            model=request.model,
        )
    except QiniuAIError as exc:
        status_code = 503 if exc.code == "qiniu_provider_not_configured" else 502
        if exc.code == "ai_source_text_too_long":
            status_code = 422
        error = ErrorResponse(code=exc.code, message=str(exc), related_ids=[])
        return JSONResponse(status_code=status_code, content=error.model_dump())

    quality_report = ValidationReport.model_validate(
        validate_screenplay(result.screenplay, result.source_texts)
    )
    if not quality_report.passed:
        error = QualityGateErrorResponse(
            code="ai_generated_screenplay_failed_quality_gate",
            message="七牛 AI 润色结果未通过质量门禁。",
            related_ids=[],
            quality_report=quality_report,
        )
        return JSONResponse(status_code=500, content=error.model_dump())
    return LocalGenerationResponse(
        screenplay=result.screenplay,
        source_texts=result.source_texts,
        issues=[ValidationIssue.model_validate(issue) for issue in result.issues],
        quality_report=quality_report,
    )
