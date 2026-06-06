"""Run one real Qiniu AI generation without printing credentials or generated text."""

from __future__ import annotations

import argparse
from typing import Any

from backend.pipeline import generate_qiniu_screenplay
from backend.providers import QiniuAIError, QiniuClient, QiniuSettings
from scripts.validate_example import validate_screenplay


SAMPLE_NOVEL = """第一章 雨夜车站
林夏在雨夜抵达车站，发现长椅下压着一封写给自己的旧信。

第二章 未寄出的信
旧信提醒林夏，父亲离开前曾把真相藏在站长室的时刻表后。

第三章 天亮之前
林夏找到时刻表后的录音。天亮时，她决定公开真相，也原谅了迟到的告别。
"""

RECOMMENDED_MODELS = (
    "deepseek-v3",
    "deepseek-v3.1",
    "deepseek/deepseek-v3.1-terminus",
    "qwen3-max",
    "moonshotai/kimi-k2.5",
)


class VerificationError(RuntimeError):
    """A safe verification failure that contains no secret or generated content."""


def select_model(models: list[str], requested: str = "", configured: str = "") -> str:
    """Choose an available model while respecting an explicit user request."""
    available = list(dict.fromkeys(model.strip() for model in models if model.strip()))
    if not available:
        raise VerificationError("七牛没有返回可用模型。")
    if requested:
        if requested not in available:
            raise VerificationError(f"指定模型不可用：{requested}")
        return requested
    if configured and configured in available:
        return configured
    recommended = next((model for model in RECOMMENDED_MODELS if model in available), "")
    return recommended or available[0]


def verify_qiniu(requested_model: str = "") -> dict[str, Any]:
    """Call Qiniu once and return only a non-sensitive verification summary."""
    settings = QiniuSettings.from_env()
    if not settings.credentials_configured:
        raise VerificationError("未检测到 QINIU_AI_API_KEY，请在当前 PowerShell 窗口设置后重试。")

    models = QiniuClient(settings).list_models()
    selected_model = select_model(models, requested_model.strip(), settings.model)
    provider = QiniuClient(settings.with_model(selected_model))
    result = generate_qiniu_screenplay(
        SAMPLE_NOVEL,
        title="七牛真实调用验收",
        client=provider,
    )
    report = validate_screenplay(result.screenplay, result.source_texts)
    if not report["passed"]:
        issue_codes = sorted({issue["code"] for issue in report["issues"]})
        raise VerificationError(f"真实 AI 结果未通过质量门禁：{', '.join(issue_codes)}")

    generation = result.screenplay.get("project", {}).get("generation", {})
    scenes = result.screenplay.get("screenplay", {}).get("scenes", [])
    warning_codes = sorted({issue["code"] for issue in result.issues})
    if generation.get("provider") != "qiniu-ai":
        raise VerificationError("生成结果未标记为七牛 AI，验收失败。")
    if generation.get("model") != selected_model:
        raise VerificationError("生成结果模型与选择模型不一致，验收失败。")
    if len(scenes) < 3:
        raise VerificationError("生成结果场次数不足，验收失败。")
    if "ai_semantic_review_required" not in warning_codes:
        raise VerificationError("生成结果缺少作者复核警告，验收失败。")

    return {
        "provider": generation["provider"],
        "model": selected_model,
        "available_model_count": len(models),
        "scene_count": len(scenes),
        "quality_gate_passed": True,
        "author_review_warning_present": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="真实调用一次七牛 AI，并只输出非敏感验收摘要。"
    )
    parser.add_argument("--model", default="", help="可选：指定七牛 /v1/models 返回的模型 ID")
    args = parser.parse_args()

    try:
        summary = verify_qiniu(args.model)
    except (QiniuAIError, VerificationError) as exc:
        code = getattr(exc, "code", "qiniu_live_verification_failed")
        print(f"FAILED: {code}: {exc}")
        return 1

    print("PASSED: real Qiniu AI generation completed.")
    print(f"provider={summary['provider']}")
    print(f"model={summary['model']}")
    print(f"available_model_count={summary['available_model_count']}")
    print(f"scene_count={summary['scene_count']}")
    print("quality_gate_passed=true")
    print("author_review_warning_present=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
