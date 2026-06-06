from __future__ import annotations

import json

import httpx
import pytest

from backend.pipeline.ai_assisted import generate_qiniu_screenplay
from backend.providers import QiniuAIError, QiniuClient, QiniuSettings
from scripts.validate_example import validate_screenplay


NOVEL = """第一章 雨夜
林夏抵达车站，发现一封旧信。

第二章 旧信
旧信指向站长室里的时刻表。

第三章 真相
林夏找到录音，并决定公开真相。
"""


def enhancements() -> dict:
    evidence_quotes = [
        "林夏抵达车站，发现一封旧信。",
        "旧信指向站长室里的时刻表。",
        "林夏找到录音，并决定公开真相。",
    ]
    return {
        "logline": "一封旧信引导林夏在天亮前找出真相。",
        "synopsis": "林夏循着旧信留下的线索，在车站找到被隐藏的录音。",
        "scenes": [
            {
                "scene_id": f"scene_{index:03d}",
                "purpose": f"推进第 {index} 个来源事件。",
                "action_text": f"{evidence_quotes[index - 1]} 镜头停留在关键线索上。",
            }
            for index in range(1, 4)
        ],
    }


class FakeQiniuClient:
    settings = QiniuSettings(api_key="secret", model="test-model")

    def complete_json(self, messages: list[dict[str, str]]) -> dict:
        assert messages[0]["role"] == "system"
        assert "不得修改 scene_id" in messages[0]["content"]
        return enhancements()


def test_qiniu_client_uses_json_object_contract_without_leaking_key() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"ok": True})}}
                ]
            },
        )

    client = QiniuClient(
        QiniuSettings(
            api_key="super-secret",
            model="chosen-model",
            base_url="https://api.qnaigc.com/v1",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.complete_json([{"role": "user", "content": "test"}]) == {"ok": True}
    assert captured["url"] == "https://api.qnaigc.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer super-secret"
    assert captured["payload"]["model"] == "chosen-model"
    assert captured["payload"]["max_tokens"] == 12_000
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_qiniu_client_requires_explicit_key_and_model() -> None:
    client = QiniuClient(QiniuSettings(api_key="", model=""))

    with pytest.raises(QiniuAIError) as error:
        client.complete_json([])

    assert error.value.code == "qiniu_provider_not_configured"
    assert "super-secret" not in repr(error.value)


def test_ai_refinement_preserves_traceability_and_passes_quality_gate() -> None:
    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=FakeQiniuClient())

    assert result.screenplay["project"]["generation"] == {
        "provider": "qiniu-ai",
        "model": "test-model",
        "mode": "qiniu_ai",
        "fallback_reason": "",
    }
    assert "林夏抵达车站，发现一封旧信。" in (
        result.screenplay["screenplay"]["scenes"][0]["beats"][0]["text"]
    )
    assert result.screenplay["narrative_events"][0]["evidence"]["quote"] in result.source_texts[
        "chapter_001"
    ]
    assert validate_screenplay(result.screenplay, result.source_texts)["passed"] is True
    assert result.issues[-1]["code"] == "ai_semantic_review_required"


def test_ai_refinement_rejects_missing_or_unknown_scene_ids() -> None:
    class IncompleteClient(FakeQiniuClient):
        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            result = enhancements()
            result["scenes"] = result["scenes"][:2]
            return result

    with pytest.raises(QiniuAIError) as error:
        generate_qiniu_screenplay(NOVEL, "雨夜来信", client=IncompleteClient())

    assert error.value.code == "qiniu_provider_output_invalid"


def test_ai_refinement_rejects_action_without_exact_evidence_quote() -> None:
    class UngroundedClient(FakeQiniuClient):
        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            result = enhancements()
            result["scenes"][0]["action_text"] = "林夏在另一个城市追逐陌生人。"
            return result

    with pytest.raises(QiniuAIError) as error:
        generate_qiniu_screenplay(NOVEL, "雨夜来信", client=UngroundedClient())

    assert error.value.code == "qiniu_provider_output_ungrounded"


def test_qiniu_client_rejects_non_json_content() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    transport = httpx.MockTransport(
        handler
    )
    client = QiniuClient(
        QiniuSettings(api_key="secret", model="model"),
        http_client=httpx.Client(transport=transport),
    )

    with pytest.raises(QiniuAIError) as error:
        client.complete_json([])

    assert error.value.code == "qiniu_provider_invalid_response"
    assert attempts == 2


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"ok": true}\n```',
        '结构化结果如下：\n{"ok": true}\n请查收。',
    ],
)
def test_qiniu_client_accepts_fenced_or_prose_wrapped_json(content: str) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )
    )
    client = QiniuClient(
        QiniuSettings(api_key="secret", model="model"),
        http_client=httpx.Client(transport=transport),
    )

    assert client.complete_json([]) == {"ok": True}


def test_qiniu_settings_use_safe_configurable_limits(monkeypatch) -> None:
    monkeypatch.setenv("QINIU_AI_TIMEOUT_SECONDS", "240")
    monkeypatch.setenv("QINIU_AI_MAX_TOKENS", "14000")

    settings = QiniuSettings.from_env()

    assert settings.timeout_seconds == 240
    assert settings.max_tokens == 14_000


def test_qiniu_client_lists_available_model_ids_without_exposing_key() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "deepseek-v3"},
                    {"id": "qwen-plus"},
                    {"id": "deepseek-v3"},
                ]
            },
        )

    client = QiniuClient(
        QiniuSettings(api_key="secret-value", model=""),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.list_models() == ["deepseek-v3", "qwen-plus"]
    assert captured["url"] == "https://api.qnaigc.com/v1/models"
    assert captured["authorization"] == "Bearer secret-value"


def test_qiniu_client_requires_key_but_not_default_model_to_list_models() -> None:
    client = QiniuClient(QiniuSettings(api_key="", model=""))

    with pytest.raises(QiniuAIError) as error:
        client.list_models()

    assert error.value.code == "qiniu_provider_not_configured"
