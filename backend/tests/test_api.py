from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.providers import QiniuAIError
from scripts.validate_example import load_example_source_texts


client = TestClient(create_app())

NOVEL = """作品信息
第一章 雨夜
林夏来到车站。

第二章 旧信
她发现了一封旧信。

第三章 真相
天亮后，真相终于揭晓。
"""


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


def test_cors_allows_configured_production_frontend(monkeypatch) -> None:
    monkeypatch.setenv("FRONTEND_ORIGINS", "https://screenplay.example.com")
    configured_client = TestClient(create_app())

    response = configured_client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://screenplay.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://screenplay.example.com"


def test_validate_returns_structured_error_for_wrong_root_type() -> None:
    response = client.post(
        "/api/v1/validate",
        json={"screenplay": ["not", "an", "object"]},
    )

    assert response.status_code == 200
    assert response.json()["passed"] is False
    assert response.json()["metrics"] == {}
    assert response.json()["issues"][0]["code"] == "schema_validation_error"


def test_parse_project_returns_serializable_chapters_and_warnings() -> None:
    response = client.post("/api/v1/projects/parse", json={"novel_text": NOVEL})

    assert response.status_code == 200
    payload = response.json()
    assert payload["eligible"] is True
    assert payload["preamble"] == "作品信息"
    assert [chapter["id"] for chapter in payload["chapters"]] == [
        "chapter_001",
        "chapter_002",
        "chapter_003",
    ]
    assert payload["chapters"][0]["text"] == "林夏来到车站。"
    assert payload["total_characters"] == len(NOVEL)
    assert {issue["code"] for issue in payload["issues"]} == {"preamble_ignored"}


def test_parse_project_returns_200_with_partial_result_below_three_chapters() -> None:
    response = client.post(
        "/api/v1/projects/parse",
        json={"novel_text": "第一章 开始\n正文一。\n第二章 继续\n正文二。"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["eligible"] is False
    assert len(payload["chapters"]) == 2
    assert payload["issues"][-1]["code"] == "chapter_count_too_low"
    assert payload["issues"][-1]["related_ids"] == ["chapter_001", "chapter_002"]


def test_parse_project_returns_200_with_empty_chapter_issue() -> None:
    response = client.post(
        "/api/v1/projects/parse",
        json={
            "novel_text": (
                "第一章 开始\n正文一。\n"
                "第二章 空章\n"
                "第三章 结束\n正文三。"
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["eligible"] is False
    empty_issue = next(issue for issue in payload["issues"] if issue["code"] == "empty_chapter")
    assert empty_issue["related_ids"] == ["chapter_002"]


def test_generate_local_returns_screenplay_sources_issues_and_quality_report() -> None:
    response = client.post(
        "/api/v1/projects/generate-local",
        json={"novel_text": NOVEL, "title": "雨夜真相"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["screenplay"]["project"]["title"] == "雨夜真相"
    assert len(payload["screenplay"]["screenplay"]["scenes"]) == 3
    assert set(payload["source_texts"]) == {
        "chapter_001",
        "chapter_002",
        "chapter_003",
    }
    assert payload["quality_report"]["passed"] is True
    assert payload["quality_report"]["metrics"]["source_traceability_coverage"] == 1.0


def test_generate_local_rejects_below_three_chapters_with_pipeline_error() -> None:
    response = client.post(
        "/api/v1/projects/generate-local",
        json={"novel_text": "第一章 开始\n正文一。\n第二章 继续\n正文二。"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "chapter_count_too_low"
    assert response.json()["related_ids"] == ["chapter_001", "chapter_002"]


def test_generate_local_rejects_empty_chapter_with_pipeline_error() -> None:
    response = client.post(
        "/api/v1/projects/generate-local",
        json={
            "novel_text": (
                "第一章 开始\n正文一。\n"
                "第二章 空章\n"
                "第三章 结束\n正文三。"
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "empty_chapter"
    assert response.json()["related_ids"] == ["chapter_002"]


def test_generate_local_rejects_source_over_character_limit() -> None:
    response = client.post(
        "/api/v1/projects/generate-local",
        json={"novel_text": "甲" * 100_001},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "source_text_too_long"


def test_parse_normalizes_bom_before_enforcing_character_limit() -> None:
    novel = "\ufeff" + NOVEL + "甲" * (100_000 - len(NOVEL))

    response = client.post("/api/v1/projects/parse", json={"novel_text": novel})

    assert response.status_code == 200
    assert response.json()["total_characters"] == 100_000


def test_project_endpoints_reject_unknown_request_fields() -> None:
    parse_response = client.post(
        "/api/v1/projects/parse",
        json={"novel_text": NOVEL, "unexpected": True},
    )
    generation_response = client.post(
        "/api/v1/projects/generate-local",
        json={"novel_text": NOVEL, "unexpected": True},
    )

    assert parse_response.status_code == 422
    assert parse_response.json()["code"] == "invalid_request"
    assert generation_response.status_code == 422
    assert generation_response.json()["code"] == "invalid_request"


def test_generate_local_rejects_more_than_one_hundred_chapters() -> None:
    novel = "\n".join(f"第{i}章 标题\n正文。" for i in range(1, 102))

    parse_response = client.post("/api/v1/projects/parse", json={"novel_text": novel})
    generation_response = client.post(
        "/api/v1/projects/generate-local",
        json={"novel_text": novel},
    )

    assert parse_response.status_code == 200
    assert len(parse_response.json()["chapters"]) == 101
    assert "chapter_count_too_high" in {
        issue["code"] for issue in parse_response.json()["issues"]
    }
    assert generation_response.status_code == 422
    assert generation_response.json()["code"] == "chapter_count_too_high"


def test_successful_generation_always_passes_quality_gate() -> None:
    response = client.post(
        "/api/v1/projects/generate-local",
        json={"novel_text": NOVEL},
    )

    assert response.status_code == 200
    assert response.json()["quality_report"]["passed"] is True


def test_validate_blocks_relabelled_generation() -> None:
    generated = client.post(
        "/api/v1/projects/generate-local",
        json={"novel_text": NOVEL},
    ).json()
    screenplay = generated["screenplay"]
    screenplay["project"]["generation"] = {
        "provider": "local-rules",
        "model": "",
        "mode": "qiniu_ai",
        "fallback_reason": "",
    }
    screenplay["screenplay"]["scenes"][0]["beats"] = [
        {"type": "action", "text": "不包含来源证据的动作。"}
    ]

    response = client.post(
        "/api/v1/validate",
        json={
            "screenplay": screenplay,
            "source_texts": generated["source_texts"],
        },
    )

    assert response.status_code == 200
    assert response.json()["passed"] is False
    assert "reference_validation_error" in {
        issue["code"] for issue in response.json()["issues"]
    }


def test_generation_quality_gate_failure_returns_diagnostics(monkeypatch) -> None:
    report = {
        "passed": False,
        "metrics": {"source_traceability_coverage": 0.0},
        "issues": [
            {
                "code": "evidence_validation_error",
                "severity": "error",
                "message": "Evidence does not match source.",
                "related_ids": ["event_001"],
            }
        ],
    }
    monkeypatch.setattr("backend.routes.validate_screenplay", lambda *_: report)

    response = client.post(
        "/api/v1/projects/generate-local",
        json={"novel_text": NOVEL},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "generated_screenplay_failed_quality_gate"
    assert response.json()["quality_report"] == report


def test_openapi_documents_project_error_response_and_text_limit() -> None:
    openapi = client.get("/openapi.json").json()

    assert (
        openapi["paths"]["/api/v1/projects/parse"]["post"]["responses"]["422"]["content"]
        ["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ErrorResponse"
    )
    assert (
        openapi["components"]["schemas"]["NovelTextRequest"]["properties"]["novel_text"][
            "maxLength"
        ]
        == 100_000
    )
    assert (
        openapi["paths"]["/api/v1/projects/generate-local"]["post"]["responses"]["500"][
            "content"
        ]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/QualityGateErrorResponse"
    )


def test_qiniu_provider_status_never_returns_api_key(monkeypatch) -> None:
    monkeypatch.setenv("QINIU_AI_API_KEY", "do-not-return")
    monkeypatch.setenv("QINIU_AI_MODEL", "configured-model")

    response = client.get("/api/v1/providers/qiniu/status")

    assert response.status_code == 200
    assert response.json()["credentials_configured"] is True
    assert response.json()["configured"] is True
    assert response.json()["model"] == "configured-model"
    assert "do-not-return" not in response.text


def test_qiniu_models_returns_non_secret_model_ids(monkeypatch) -> None:
    monkeypatch.setenv("QINIU_AI_API_KEY", "do-not-return")
    monkeypatch.setenv("QINIU_AI_MODEL", "deepseek-v3")
    monkeypatch.setattr(
        "backend.routes.QiniuClient.list_models",
        lambda self: ["deepseek-v3", "qwen-plus"],
    )

    response = client.get("/api/v1/providers/qiniu/models")

    assert response.status_code == 200
    assert response.json()["selected_model"] == "deepseek-v3"
    assert response.json()["models"] == ["deepseek-v3", "qwen-plus"]
    assert "do-not-return" not in response.text


def test_generate_ai_returns_not_configured_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("QINIU_AI_API_KEY", raising=False)
    monkeypatch.delenv("QINIU_AI_MODEL", raising=False)

    response = client.post(
        "/api/v1/projects/generate-ai",
        json={"novel_text": NOVEL, "title": "雨夜真相"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "qiniu_provider_not_configured"


def test_generate_ai_validates_chapters_before_calling_provider(monkeypatch) -> None:
    def should_not_run(*args, **kwargs):
        raise AssertionError("provider pipeline must not run")

    monkeypatch.setattr("backend.routes.generate_qiniu_screenplay", should_not_run)
    response = client.post(
        "/api/v1/projects/generate-ai",
        json={"novel_text": "第一章 开始\n正文。\n第二章 继续\n正文。"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "chapter_count_too_low"


def test_generate_ai_returns_actionable_provider_diagnostics(monkeypatch) -> None:
    def fail_with_diagnostics(*args, **kwargs):
        raise QiniuAIError(
            "qiniu_provider_output_invalid",
            "七牛 AI 自动修复后仍未通过完整结构校验。",
            diagnostics=[
                {
                    "code": "ai_character_reference_ambiguous",
                    "severity": "error",
                    "message": "场次 5 的人物称谓 Guide 存在歧义；关联剧情：穿过尸洞。",
                    "related_ids": ["scene_005"],
                }
            ],
        )

    monkeypatch.setattr("backend.routes.generate_qiniu_screenplay", fail_with_diagnostics)
    response = client.post(
        "/api/v1/projects/generate-ai",
        json={"novel_text": NOVEL, "title": "七牛润色"},
    )

    assert response.status_code == 502
    assert response.json()["diagnostics"][0]["related_ids"] == ["scene_005"]
    assert "Guide" in response.json()["diagnostics"][0]["message"]


def test_generate_ai_returns_quality_gated_result(monkeypatch) -> None:
    from backend.pipeline import generate_local_screenplay

    generated = generate_local_screenplay(NOVEL, title="七牛润色")
    generated.screenplay["project"]["generation"] = {
        "provider": "qiniu-ai",
        "model": "mock-model",
        "mode": "qiniu_ai",
        "fallback_reason": "",
    }
    monkeypatch.setattr(
        "backend.routes.generate_qiniu_screenplay",
        lambda *args, **kwargs: generated,
    )

    response = client.post(
        "/api/v1/projects/generate-ai",
        json={"novel_text": NOVEL, "title": "七牛润色"},
    )

    assert response.status_code == 200
    assert response.json()["screenplay"]["project"]["generation"]["mode"] == "qiniu_ai"
    assert response.json()["quality_report"]["passed"] is True


def test_generate_ai_blocks_result_that_fails_quality_gate(monkeypatch) -> None:
    from backend.pipeline import generate_local_screenplay

    generated = generate_local_screenplay(NOVEL, title="七牛润色")
    monkeypatch.setattr(
        "backend.routes.generate_qiniu_screenplay",
        lambda *args, **kwargs: generated,
    )
    monkeypatch.setattr(
        "backend.routes.validate_screenplay",
        lambda *args, **kwargs: {
            "passed": False,
            "metrics": {"source_traceability_coverage": 0.0},
            "issues": [
                {
                    "code": "evidence_validation_error",
                    "severity": "error",
                    "message": "Evidence mismatch.",
                    "related_ids": ["event_001"],
                }
            ],
        },
    )

    response = client.post(
        "/api/v1/projects/generate-ai",
        json={"novel_text": NOVEL, "title": "七牛润色"},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "ai_generated_screenplay_failed_quality_gate"
    assert response.json()["quality_report"]["passed"] is False


def test_generate_ai_passes_user_selected_model_to_provider_pipeline(monkeypatch) -> None:
    from backend.pipeline import generate_local_screenplay

    captured: dict = {}

    def fake_generate(novel_text: str, title: str, model: str, scene_density: str):
        captured["model"] = model
        captured["scene_density"] = scene_density
        return generate_local_screenplay(novel_text, title=title)

    monkeypatch.setattr("backend.routes.generate_qiniu_screenplay", fake_generate)
    response = client.post(
        "/api/v1/projects/generate-ai",
        json={
            "novel_text": NOVEL,
            "title": "七牛润色",
            "model": "deepseek-v3",
            "scene_density": "detailed",
        },
    )

    assert response.status_code == 200
    assert captured["model"] == "deepseek-v3"
    assert captured["scene_density"] == "detailed"
