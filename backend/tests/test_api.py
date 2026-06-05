from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from backend.main import create_app
from scripts.validate_example import load_example_source_texts


client = TestClient(create_app())


def load_example() -> dict:
    response = client.get("/api/v1/example")
    assert response.status_code == 200
    return response.json()


def test_health_check() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-novel-to-script-api",
        "version": "0.1.0",
    }


def test_example_returns_parsed_yaml_object() -> None:
    response = client.get("/api/v1/example")

    assert response.status_code == 200
    assert response.json()["schema_version"] == "1.0.0"
    assert len(response.json()["source"]["chapters"]) >= 3


def test_validate_accepts_valid_example_with_source_texts() -> None:
    response = client.post(
        "/api/v1/validate",
        json={
            "screenplay": load_example(),
            "source_texts": load_example_source_texts(),
        },
    )

    assert response.status_code == 200
    assert response.json()["passed"] is True
    assert response.json()["issues"] == []
    assert response.json()["metrics"]["source_traceability_coverage"] == 1.0


def test_validate_returns_structured_schema_errors() -> None:
    screenplay = copy.deepcopy(load_example())
    del screenplay["project"]

    response = client.post("/api/v1/validate", json={"screenplay": screenplay})

    assert response.status_code == 200
    assert response.json()["passed"] is False
    assert response.json()["metrics"] == {}
    assert response.json()["issues"][0]["code"] == "schema_validation_error"


def test_validate_allows_omitting_optional_source_texts() -> None:
    response = client.post("/api/v1/validate", json={"screenplay": load_example()})

    assert response.status_code == 200
    assert response.json()["passed"] is False
    assert response.json()["issues"][0]["code"] == "evidence_validation_error"


def test_validate_rejects_request_without_screenplay() -> None:
    response = client.post("/api/v1/validate", json={})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_validate_rejects_unknown_request_field() -> None:
    response = client.post(
        "/api/v1/validate",
        json={"screenplay": load_example(), "source_text": "misspelled"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_request",
        "message": "Request body does not match the API contract.",
        "related_ids": [],
    }


def test_validate_rejects_source_texts_over_limit() -> None:
    response = client.post(
        "/api/v1/validate",
        json={"screenplay": load_example(), "source_texts": {"chapter_1": "x" * 100_001}},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_cors_allows_local_frontend() -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in response.headers


def test_validate_returns_structured_error_for_wrong_root_type() -> None:
    response = client.post(
        "/api/v1/validate",
        json={"screenplay": ["not", "an", "object"]},
    )

    assert response.status_code == 200
    assert response.json()["passed"] is False
    assert response.json()["metrics"] == {}
    assert response.json()["issues"][0]["code"] == "schema_validation_error"
