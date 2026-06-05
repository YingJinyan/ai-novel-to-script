"""API request and response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_SOURCE_CHARACTERS = 100_000


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    screenplay: Any
    source_texts: dict[str, str] = Field(default_factory=dict)

    @field_validator("source_texts")
    @classmethod
    def enforce_source_text_limit(cls, source_texts: dict[str, str]) -> dict[str, str]:
        if sum(len(text) for text in source_texts.values()) > MAX_SOURCE_CHARACTERS:
            raise ValueError(f"source_texts exceeds {MAX_SOURCE_CHARACTERS} characters")
        return source_texts


class ValidationIssue(BaseModel):
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    related_ids: list[str]


class ValidationReport(BaseModel):
    passed: bool
    metrics: dict[str, float | int]
    issues: list[ValidationIssue]


class ErrorResponse(BaseModel):
    code: str
    message: str
    related_ids: list[str] = Field(default_factory=list)
