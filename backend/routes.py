"""HTTP routes for the screenplay backend."""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from backend.models import HealthResponse, ValidationReport, ValidationRequest
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


@router.post("/validate", response_model=ValidationReport)
def validate(request: ValidationRequest) -> dict:
    """Validate a screenplay and return its structured quality report."""
    return validate_screenplay(request.screenplay, request.source_texts)
