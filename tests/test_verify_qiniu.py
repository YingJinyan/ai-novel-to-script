from __future__ import annotations

import copy

import pytest

from backend.pipeline import generate_local_screenplay
from scripts.verify_qiniu import SAMPLE_NOVEL, VerificationError, select_model, verify_full_ai_structure


def test_select_model_respects_an_available_explicit_request() -> None:
    assert (
        select_model(["deepseek-v3", "qwen3-max"], requested="qwen3-max")
        == "qwen3-max"
    )


def test_select_model_rejects_an_unavailable_explicit_request() -> None:
    with pytest.raises(VerificationError, match="指定模型不可用"):
        select_model(["deepseek-v3"], requested="not-a-model")


def test_select_model_prefers_an_available_configured_default() -> None:
    assert (
        select_model(
            ["deepseek-v3", "qwen3-max"],
            configured="qwen3-max",
        )
        == "qwen3-max"
    )


def test_select_model_prefers_a_recommended_model_over_first_available() -> None:
    assert (
        select_model(["qwen2.5-vl-7b-instruct", "deepseek-v3", "deepseek-r1"])
        == "deepseek-v3"
    )


def test_full_ai_structure_rejects_a_fallback_with_only_an_ai_label() -> None:
    local = generate_local_screenplay(SAMPLE_NOVEL, title="验收").screenplay
    label_only = copy.deepcopy(local)
    label_only["project"]["generation"] = {
        "provider": "qiniu-ai",
        "model": "deepseek-v3",
        "mode": "qiniu_ai",
        "fallback_reason": "",
    }

    with pytest.raises(VerificationError, match="未提取人物"):
        verify_full_ai_structure(label_only, local)


def test_full_ai_structure_accepts_substantive_adaptation() -> None:
    local = generate_local_screenplay(SAMPLE_NOVEL, title="验收").screenplay
    adapted = copy.deepcopy(local)
    adapted["story_bible"]["characters"] = [{"id": "character_001", "name": "林夏"}]
    adapted["story_bible"]["locations"] = [{"id": "location_001", "name": "雨夜车站"}]
    adapted["screenplay"]["scenes"][0]["beats"].append(
        {"type": "action", "text": "林夏捡起旧信。"}
    )

    summary = verify_full_ai_structure(adapted, local)

    assert summary == {
        "character_count": 1,
        "location_count": 1,
        "event_count": 3,
        "scene_count": 3,
        "beat_count": 4,
    }
