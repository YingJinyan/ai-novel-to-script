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
    diagnostics: list[ValidationIssue] = Field(default_factory=list)

    def response_content(self) -> dict[str, Any]:
        """Keep the established error shape while adding diagnostics only when useful."""
        return self.model_dump(exclude={"diagnostics"} if not self.diagnostics else set())


class QualityGateErrorResponse(ErrorResponse):
    quality_report: ValidationReport


class NovelTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_text: str = Field(
        max_length=MAX_SOURCE_CHARACTERS,
        description=f"Novel text containing chapter headings; maximum {MAX_SOURCE_CHARACTERS} characters.",
    )

    @field_validator("novel_text", mode="before")
    @classmethod
    def normalize_novel_text(cls, novel_text: Any) -> Any:
        if not isinstance(novel_text, str):
            return novel_text
        return novel_text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


class LocalGenerationRequest(NovelTextRequest):
    title: str = Field(default="本地规则改编", min_length=1, max_length=200)


class AIGenerationRequest(LocalGenerationRequest):
    model: str = Field(default="", max_length=200)
    scene_density: Literal["concise", "balanced", "detailed"] = "concise"


class ParsedChapter(BaseModel):
    id: str
    order: int = Field(ge=1)
    title: str
    text: str


class ChapterParseResponse(BaseModel):
    eligible: bool
    chapters: list[ParsedChapter]
    preamble: str
    total_characters: int = Field(ge=0)
    issues: list[ValidationIssue]


class LocalGenerationResponse(BaseModel):
    screenplay: dict[str, Any]
    source_texts: dict[str, str]
    issues: list[ValidationIssue]
    quality_report: ValidationReport


class ProviderStatusResponse(BaseModel):
    provider: str
    credentials_configured: bool
    configured: bool
    model: str
    base_url: str
    mode: str


class ProviderModelsResponse(BaseModel):
    provider: str
    selected_model: str
    models: list[str]
