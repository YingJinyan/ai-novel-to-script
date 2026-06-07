from __future__ import annotations

import copy
import json

import httpx
import pytest

from backend.pipeline.ai_assisted import _evidence_candidates, _prompt, generate_qiniu_screenplay
from backend.pipeline.local_rules import generate_local_screenplay
from backend.providers import QiniuAIError, QiniuClient, QiniuSettings
from scripts.validate_example import validate_screenplay


NOVEL = """第一章 雨夜
林夏抵达车站，发现一封旧信。

第二章 旧信
旧信指向站长室里的时刻表。

第三章 真相
林夏找到录音，并决定公开真相。
"""


def full_adaptation() -> dict:
    return {
        "logline": "一封旧信引导林夏在天亮前找出真相。",
        "premise": "林夏循着旧信，在废弃车站追查被隐藏的真相。",
        "synopsis": "林夏循着旧信留下的线索，在车站找到被隐藏的录音。",
        "characters": [
            {
                "name": "林夏",
                "aliases": [],
                "role": "protagonist",
                "description": "追查旧信真相的年轻人。",
                "goal": "找到录音并公开真相。",
            }
        ],
        "locations": [
            {"name": "废弃车站", "description": "林夏发现旧信的车站。"},
            {"name": "站长室", "description": "藏有时刻表和录音的房间。"},
        ],
        "events": [
            {
                "chapter_id": f"chapter_{index:03d}",
                "summary": summary,
                "importance": "critical" if index == 1 else "major",
                "evidence_id": f"chapter_{index:03d}_evidence_001",
            }
            for index, summary in enumerate(
                ["林夏发现旧信", "旧信指向时刻表", "林夏找到录音并公开真相"],
                start=1,
            )
        ],
        "scenes": [
            {
                "int_ext": "INT",
                "location_name": "废弃车站" if index == 1 else "站长室",
                "time_of_day": "夜",
                "purpose": f"推进第 {index} 个来源事件。",
                "character_names": ["林夏"],
                "source_event_numbers": [index],
                "beats": [
                    {
                        "type": "action",
                        "text": f"林夏以可表演动作推进事件 {index}。",
                        "character_name": "",
                        "parenthetical": "",
                    }
                ],
            }
            for index in range(1, 4)
        ],
    }


class FakeQiniuClient:
    settings = QiniuSettings(api_key="secret", model="test-model")

    def complete_json(self, messages: list[dict[str, str]]) -> dict:
        assert messages[0]["role"] == "system"
        assert "证据单元" in messages[0]["content"]
        assert "evidence_id" in messages[1]["content"]
        return full_adaptation()


def test_evidence_candidates_merge_adjacent_sentences_without_losing_source_positions() -> None:
    result = generate_local_screenplay(
        "第一章 一\n第一句很短。第二句也很短。\n"
        "第二章 二\n第三句。\n"
        "第三章 三\n第四句。"
    )

    candidates = _evidence_candidates(result)
    first = candidates[0]

    assert first["quote"] == "第一句很短。第二句也很短。"
    assert (
        result.source_texts[first["chapter_id"]][first["start_char"]:first["end_char"]]
        == first["quote"]
    )


def test_ai_prompt_requires_explicit_event_dramatization() -> None:
    result = generate_local_screenplay(NOVEL)
    messages = _prompt(result, _evidence_candidates(result), "balanced")

    assert "本次要求总场次数为 5 到 9" in messages[1]["content"]
    assert "每个来源事件都必须在关联场次的动作或对白中被明确演出来" in messages[1]["content"]
    assert "不能只填写 source_event_numbers 来声称覆盖" in messages[1]["content"]
    assert "输出语言必须与原文一致" in messages[0]["content"]
    assert "中文原文必须使用中文人物名" in messages[0]["content"]


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


def test_full_ai_adaptation_extracts_structure_and_passes_quality_gate() -> None:
    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=FakeQiniuClient())

    assert result.screenplay["project"]["generation"] == {
        "provider": "qiniu-ai",
        "model": "test-model",
        "mode": "qiniu_ai",
        "fallback_reason": "",
    }
    assert result.screenplay["story_bible"]["characters"][0]["name"] == "林夏"
    assert {location["name"] for location in result.screenplay["story_bible"]["locations"]} == {
        "废弃车站",
        "站长室",
    }
    assert "林夏抵达车站，发现一封旧信。" not in (
        result.screenplay["screenplay"]["scenes"][0]["beats"][0]["text"]
    )
    assert result.screenplay["narrative_events"][0]["evidence"]["quote"] in result.source_texts[
        "chapter_001"
    ]
    assert validate_screenplay(result.screenplay, result.source_texts)["passed"] is True
    assert result.issues[-1]["code"] == "ai_semantic_review_required"
    serialized = json.dumps(result.screenplay, ensure_ascii=False)
    assert serialized.count("qiniu-ai") == 1
    assert "七牛 AI 根据来源事件" not in serialized


def test_full_ai_adaptation_deduplicates_character_aliases() -> None:
    class DuplicateAliasClient(FakeQiniuClient):
        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            result = full_adaptation()
            result["characters"][0]["aliases"] = ["林夏", " 小林 ", "小林"]
            return result

    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=DuplicateAliasClient())

    assert result.screenplay["story_bible"]["characters"][0]["aliases"] == ["小林"]
    assert validate_screenplay(result.screenplay, result.source_texts)["passed"] is True


def test_full_ai_adaptation_resolves_unique_location_name_variation_without_retry() -> None:
    class VariantLocationClient(FakeQiniuClient):
        calls = 0

        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            self.calls += 1
            result = full_adaptation()
            result["scenes"][2]["location_name"] = "狭窄站长室"
            return result

    client = VariantLocationClient()
    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=client)

    assert client.calls == 1
    assert len(result.screenplay["story_bible"]["locations"]) == 2
    assert result.screenplay["screenplay"]["scenes"][2]["heading"]["location_id"] == "location_002"
    assert "ai_location_reference_normalized" in {issue["code"] for issue in result.issues}


def test_full_ai_adaptation_registers_scene_only_location_for_author_review() -> None:
    class NewLocationClient(FakeQiniuClient):
        calls = 0

        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            self.calls += 1
            result = full_adaptation()
            result["scenes"][2]["location_name"] = "车站月台"
            return result

    client = NewLocationClient()
    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=client)

    assert client.calls == 1
    assert result.screenplay["story_bible"]["locations"][-1]["name"] == "车站月台"
    assert result.screenplay["story_bible"]["locations"][-1]["description"] == (
        "根据场次内容补充的地点，具体设定需由作者复核。"
    )
    assert result.screenplay["screenplay"]["scenes"][2]["heading"]["location_id"] == "location_003"
    assert "ai_location_review_required" in {issue["code"] for issue in result.issues}
    assert validate_screenplay(result.screenplay, result.source_texts)["passed"] is True


def test_full_ai_adaptation_registers_scene_only_character_for_author_review() -> None:
    class NewCharacterClient(FakeQiniuClient):
        calls = 0

        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            self.calls += 1
            result = full_adaptation()
            result["scenes"][2]["character_names"].append("Guide")
            result["scenes"][2]["beats"].append(
                {
                    "type": "dialogue",
                    "text": "请从这里离开。",
                    "character_name": "Guide",
                    "parenthetical": "",
                }
            )
            return result

    client = NewCharacterClient()
    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=client)

    inferred = result.screenplay["story_bible"]["characters"][-1]
    assert client.calls == 1
    assert inferred["name"] == "Guide"
    assert inferred["role"] == "minor"
    assert result.screenplay["screenplay"]["scenes"][2]["beats"][-1]["character_id"] == inferred["id"]
    assert "ai_character_review_required" in {issue["code"] for issue in result.issues}
    assert validate_screenplay(result.screenplay, result.source_texts)["passed"] is True


def test_full_ai_adaptation_adds_characters_explicitly_mentioned_in_beats() -> None:
    class MentionedCharacterClient(FakeQiniuClient):
        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            result = full_adaptation()
            result["characters"].append(
                {
                    "name": "站长",
                    "aliases": [],
                    "role": "supporting",
                    "description": "车站的站长。",
                    "goal": "保护录音。",
                }
            )
            result["scenes"][1]["beats"][0]["text"] = "站长挡在门前，林夏停下脚步。"
            return result

    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=MentionedCharacterClient())

    assert result.screenplay["screenplay"]["scenes"][1]["character_ids"] == [
        "character_001",
        "character_002",
    ]


def test_full_ai_adaptation_warns_when_multiple_events_are_overcompressed() -> None:
    class CompressedSceneClient(FakeQiniuClient):
        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            result = full_adaptation()
            result["scenes"][0]["source_event_numbers"] = [1, 2]
            return result

    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=CompressedSceneClient())

    issue = next(
        issue for issue in result.issues if issue["code"] == "ai_scene_compression_review_required"
    )
    assert "场次 1" in issue["message"]
    assert "林夏发现旧信" in issue["message"]
    assert issue["related_ids"] == ["scene_001", "event_001", "event_002"]


def test_full_ai_adaptation_recovers_unmapped_event_with_same_chapter_scene() -> None:
    class UnmappedEventClient(FakeQiniuClient):
        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            result = full_adaptation()
            result["events"].append(
                {
                    "chapter_id": "chapter_001",
                    "summary": "林夏确认旧信来自父亲",
                    "importance": "major",
                    "evidence_id": "chapter_001_evidence_001",
                }
            )
            return result

    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=UnmappedEventClient())

    first_scene = result.screenplay["screenplay"]["scenes"][0]
    assert first_scene["traceability"]["source_event_ids"] == ["event_001", "event_004"]
    issue = next(
        issue for issue in result.issues if issue["code"] == "ai_event_mapping_review_required"
    )
    assert "林夏确认旧信来自父亲" in issue["message"]
    assert issue["related_ids"] == ["event_004", "scene_001"]
    assert validate_screenplay(result.screenplay, result.source_texts)["passed"] is True


def test_full_ai_adaptation_reports_ambiguous_character_with_scene_and_plot_context() -> None:
    class AmbiguousCharacterClient(FakeQiniuClient):
        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            result = full_adaptation()
            result["characters"][0]["name"] = "林夏雨"
            result["characters"].append(
                {
                    "name": "林夏雪",
                    "aliases": [],
                    "role": "supporting",
                    "description": "另一名参与调查的人。",
                    "goal": "找到录音。",
                }
            )
            return result

    with pytest.raises(QiniuAIError) as error:
        generate_qiniu_screenplay(NOVEL, "雨夜来信", client=AmbiguousCharacterClient())

    assert error.value.diagnostics[0]["code"] == "ai_character_reference_ambiguous"
    assert "场次 1" in error.value.diagnostics[0]["message"]
    assert "林夏发现旧信" in error.value.diagnostics[0]["message"]
    assert "林夏" in error.value.diagnostics[0]["message"]


def test_full_ai_adaptation_repairs_missing_structure_once() -> None:
    class RepairClient(FakeQiniuClient):
        calls = 0

        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            self.calls += 1
            result = full_adaptation()
            if self.calls == 1:
                del result["characters"][0]["goal"]
            else:
                assert "characters.0.goal" in messages[-1]["content"]
            return result

    client = RepairClient()
    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=client)

    assert client.calls == 2
    assert result.screenplay["story_bible"]["characters"][0]["goal"] == "找到录音并公开真相。"


def test_balanced_scene_density_repairs_an_overcompressed_result() -> None:
    class DensityRepairClient(FakeQiniuClient):
        calls = 0

        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            self.calls += 1
            result = full_adaptation()
            if self.calls == 2:
                result["scenes"].extend(
                    [copy.deepcopy(result["scenes"][1]), copy.deepcopy(result["scenes"][2])]
                )
            return result

    client = DensityRepairClient()
    result = generate_qiniu_screenplay(
        NOVEL,
        "雨夜来信",
        scene_density="balanced",
        client=client,
    )

    assert client.calls == 2
    assert len(result.screenplay["screenplay"]["scenes"]) == 5
    assert result.screenplay["adaptation_control"]["target_scene_count"] == 7
    assert result.screenplay["adaptation_control"]["scene_count_range"] == {
        "minimum": 5,
        "maximum": 9,
    }
    report = validate_screenplay(result.screenplay, result.source_texts)
    assert report["metrics"]["target_scene_delta"] == 0
    assert "target_scene_count_mismatch" not in {
        issue["code"] for issue in report["issues"]
    }


def test_chinese_source_repairs_a_predominantly_english_adaptation() -> None:
    class LanguageRepairClient(FakeQiniuClient):
        calls = 0

        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            self.calls += 1
            result = full_adaptation()
            if self.calls == 1:
                result["logline"] = "A long English adaptation " * 8
                result["premise"] = "English premise " * 10
                result["synopsis"] = "English synopsis " * 10
                for event in result["events"]:
                    event["summary"] = "English event summary " * 10
                for scene in result["scenes"]:
                    scene["purpose"] = "English purpose " * 10
                    for beat in scene["beats"]:
                        beat["text"] = "English screenplay action and dialogue " * 10
            else:
                assert "输出语言与原文不一致" in messages[-1]["content"]
            return result

    client = LanguageRepairClient()
    result = generate_qiniu_screenplay(NOVEL, "雨夜来信", client=client)

    assert client.calls == 2
    assert result.screenplay["screenplay"]["synopsis"] == "林夏循着旧信留下的线索，在车站找到被隐藏的录音。"


def test_chinese_source_blocks_persistently_english_adaptation_with_diagnostic() -> None:
    class EnglishOnlyClient(FakeQiniuClient):
        calls = 0

        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            self.calls += 1
            result = full_adaptation()
            result["logline"] = "A long English adaptation " * 8
            result["premise"] = "English premise " * 10
            result["synopsis"] = "English synopsis " * 10
            for event in result["events"]:
                event["summary"] = "English event summary " * 10
            for scene in result["scenes"]:
                scene["purpose"] = "English purpose " * 10
                for beat in scene["beats"]:
                    beat["text"] = "English screenplay action and dialogue " * 10
            return result

    client = EnglishOnlyClient()
    with pytest.raises(QiniuAIError) as error:
        generate_qiniu_screenplay(NOVEL, "雨夜来信", client=client)

    assert client.calls == 2
    assert error.value.diagnostics[0]["code"] == "ai_output_language_mismatch"
    assert "输出语言与原文不一致" in str(error.value)


def test_full_ai_adaptation_reports_specific_issue_after_failed_repair() -> None:
    class InvalidClient(FakeQiniuClient):
        calls = 0

        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            self.calls += 1
            result = full_adaptation()
            del result["characters"][0]["goal"]
            return result

    client = InvalidClient()
    with pytest.raises(QiniuAIError) as error:
        generate_qiniu_screenplay(NOVEL, "雨夜来信", client=client)

    assert client.calls == 2
    assert error.value.code == "qiniu_provider_output_invalid"
    assert "characters.0.goal" in str(error.value)


def test_full_ai_adaptation_rejects_unmapped_event_without_same_chapter_scene() -> None:
    class IncompleteClient(FakeQiniuClient):
        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            result = full_adaptation()
            result["scenes"][2]["source_event_numbers"] = [2]
            return result

    with pytest.raises(QiniuAIError) as error:
        generate_qiniu_screenplay(NOVEL, "雨夜来信", client=IncompleteClient())

    assert error.value.code == "qiniu_provider_output_invalid"
    assert error.value.diagnostics[0]["code"] == "ai_event_scene_missing"


def test_full_ai_adaptation_rejects_unknown_evidence_id() -> None:
    class UnknownEvidenceClient(FakeQiniuClient):
        def complete_json(self, messages: list[dict[str, str]]) -> dict:
            result = full_adaptation()
            result["events"][0]["evidence_id"] = "unknown_evidence"
            return result

    with pytest.raises(QiniuAIError) as error:
        generate_qiniu_screenplay(NOVEL, "雨夜来信", client=UnknownEvidenceClient())

    assert error.value.code == "qiniu_provider_output_invalid"


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


def test_qiniu_client_reports_connection_interrupted_during_generation() -> None:
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.ReadError("closed", request=request))
    )
    client = QiniuClient(
        QiniuSettings(api_key="secret", model="deepseek-v3.1"),
        http_client=httpx.Client(transport=transport),
    )

    with pytest.raises(QiniuAIError) as error:
        client.complete_json([])

    assert error.value.code == "qiniu_provider_connection_interrupted"
    assert "deepseek-v3" in str(error.value)


def test_qiniu_client_reports_failure_to_establish_connection() -> None:
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline", request=request))
    )
    client = QiniuClient(
        QiniuSettings(api_key="secret", model="deepseek-v3"),
        http_client=httpx.Client(transport=transport),
    )

    with pytest.raises(QiniuAIError) as error:
        client.complete_json([])

    assert error.value.code == "qiniu_provider_connection_error"
    assert "无法建立" in str(error.value)


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
