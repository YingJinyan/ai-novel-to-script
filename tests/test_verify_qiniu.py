from __future__ import annotations

import pytest

from scripts.verify_qiniu import VerificationError, select_model


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
