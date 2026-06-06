"""Qiniu OpenAI-compatible chat completion client."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from dataclasses import replace
from typing import Any

import httpx


DEFAULT_QINIU_BASE_URL = "https://api.qnaigc.com/v1"


class QiniuAIError(RuntimeError):
    """A safe, structured provider failure that never exposes credentials."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class QiniuSettings:
    api_key: str
    model: str
    base_url: str = DEFAULT_QINIU_BASE_URL
    timeout_seconds: float = 180.0
    max_tokens: int = 12_000

    @classmethod
    def from_env(cls) -> "QiniuSettings":
        timeout = os.getenv("QINIU_AI_TIMEOUT_SECONDS", "180")
        try:
            timeout_seconds = max(1.0, min(float(timeout), 300.0))
        except ValueError:
            timeout_seconds = 180.0
        max_tokens = os.getenv("QINIU_AI_MAX_TOKENS", "12000")
        try:
            parsed_max_tokens = max(1_000, min(int(max_tokens), 16_000))
        except ValueError:
            parsed_max_tokens = 12_000
        return cls(
            api_key=os.getenv("QINIU_AI_API_KEY", "").strip(),
            model=os.getenv("QINIU_AI_MODEL", "").strip(),
            base_url=os.getenv("QINIU_AI_BASE_URL", DEFAULT_QINIU_BASE_URL).strip().rstrip("/"),
            timeout_seconds=timeout_seconds,
            max_tokens=parsed_max_tokens,
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model and self.base_url)

    @property
    def credentials_configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def with_model(self, model: str) -> "QiniuSettings":
        return replace(self, model=model.strip())


class QiniuClient:
    """Call Qiniu's OpenAI-compatible endpoint and require a JSON object."""

    def __init__(
        self,
        settings: QiniuSettings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or QiniuSettings.from_env()
        self._http_client = http_client

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not self.settings.configured:
            raise QiniuAIError(
                "qiniu_provider_not_configured",
                "七牛 AI 未配置。请设置 QINIU_AI_API_KEY 与 QINIU_AI_MODEL。",
            )

        client = self._http_client or httpx.Client(timeout=self.settings.timeout_seconds)
        should_close = self._http_client is None
        try:
            for attempt in range(2):
                retry_messages = messages
                if attempt:
                    retry_messages = [
                        *messages,
                        {
                            "role": "system",
                            "content": (
                                "上次响应不是可解析的 JSON 对象。请重新生成，只返回一个完整 JSON 对象，"
                                "不要使用 Markdown 代码块，不要添加解释文字。"
                            ),
                        },
                    ]
                response = client.post(
                    f"{self.settings.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.api_key}"},
                    json={
                        "model": self.settings.model,
                        "messages": retry_messages,
                        "stream": False,
                        "temperature": 0.1,
                        "max_tokens": self.settings.max_tokens,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                parsed = self._response_json_object(response)
                if parsed is not None:
                    return parsed
        except httpx.TimeoutException as exc:
            raise QiniuAIError(
                "qiniu_provider_timeout",
                "七牛 AI 请求超时。建议改用快速文本模型，或提高 QINIU_AI_TIMEOUT_SECONDS。",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise QiniuAIError(
                "qiniu_provider_http_error",
                f"七牛 AI 返回 HTTP {exc.response.status_code}。",
            ) from exc
        except (httpx.ReadError, httpx.RemoteProtocolError) as exc:
            raise QiniuAIError(
                "qiniu_provider_connection_interrupted",
                "七牛 AI 连接在生成期间中断。该模型可能响应过慢或上游关闭连接；"
                "建议改用 deepseek-v3 或 qwen3-max 后重试。",
            ) from exc
        except httpx.ConnectError as exc:
            raise QiniuAIError(
                "qiniu_provider_connection_error",
                "无法建立七牛 AI 连接。请检查网络后重试；演示时建议使用 deepseek-v3 或 qwen3-max。",
            ) from exc
        except httpx.HTTPError as exc:
            raise QiniuAIError(
                "qiniu_provider_connection_error",
                "七牛 AI 网络请求失败。请检查网络，并改用 deepseek-v3 或 qwen3-max 重试。",
            ) from exc
        finally:
            if should_close:
                client.close()

        raise QiniuAIError(
            "qiniu_provider_invalid_response",
            "七牛 AI 自动重试后仍未返回完整 JSON 对象。建议改用 deepseek-v3、qwen3-max 等文本模型。",
        )

    @staticmethod
    def _response_json_object(response: httpx.Response) -> dict[str, Any] | None:
        """Parse strict, fenced, or prose-wrapped JSON without accepting non-objects."""
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        if not isinstance(content, str):
            return None

        candidates = [content.strip()]
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL | re.IGNORECASE)
        if fenced:
            candidates.append(fenced.group(1))
        candidates.extend(content[index:] for index, character in enumerate(content) if character == "{")
        decoder = json.JSONDecoder()
        for candidate in candidates:
            try:
                parsed, _ = decoder.raw_decode(candidate.lstrip())
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def list_models(self) -> list[str]:
        """Return model IDs available to the configured Qiniu account."""
        if not self.settings.credentials_configured:
            raise QiniuAIError(
                "qiniu_provider_not_configured",
                "七牛 AI 未配置。请设置 QINIU_AI_API_KEY。",
            )

        client = self._http_client or httpx.Client(timeout=self.settings.timeout_seconds)
        should_close = self._http_client is None
        try:
            response = client.get(
                f"{self.settings.base_url}/models",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise QiniuAIError("qiniu_provider_timeout", "七牛 AI 模型列表请求超时。") from exc
        except httpx.HTTPStatusError as exc:
            raise QiniuAIError(
                "qiniu_provider_http_error",
                f"七牛 AI 模型列表返回 HTTP {exc.response.status_code}。",
            ) from exc
        except httpx.HTTPError as exc:
            raise QiniuAIError("qiniu_provider_connection_error", "无法连接七牛 AI。") from exc
        finally:
            if should_close:
                client.close()

        try:
            data = response.json()["data"]
            model_ids = sorted(
                {
                    item["id"].strip()
                    for item in data
                    if isinstance(item, dict)
                    and isinstance(item.get("id"), str)
                    and item["id"].strip()
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise QiniuAIError(
                "qiniu_provider_invalid_response",
                "七牛 AI 未返回可解析的模型列表。",
            ) from exc
        if not model_ids:
            raise QiniuAIError(
                "qiniu_provider_invalid_response",
                "七牛 AI 返回的模型列表为空。",
            )
        return model_ids
