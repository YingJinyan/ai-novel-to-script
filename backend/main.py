"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.models import ErrorResponse, MAX_SOURCE_CHARACTERS
from backend.routes import router


def create_app() -> FastAPI:
    """Create the API application with development-friendly defaults."""
    application = FastAPI(
        title="AI Novel to Script API",
        description="Validation and example APIs for traceable screenplay YAML.",
        version="0.1.0",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        novel_too_long = any(
            error["type"] == "string_too_long"
            and tuple(error["loc"][-2:]) == ("body", "novel_text")
            for error in exc.errors()
        )
        error = ErrorResponse(
            code="source_text_too_long" if novel_too_long else "invalid_request",
            message=(
                f"Novel text cannot exceed {MAX_SOURCE_CHARACTERS} normalized characters."
                if novel_too_long
                else "Request body does not match the API contract."
            ),
            related_ids=[],
        )
        return JSONResponse(status_code=422, content=error.model_dump())

    application.include_router(router, prefix="/api/v1")
    return application


app = create_app()
