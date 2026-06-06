"""Qiniu OpenAI-compatible chat completion client."""

from __future__ import annotations

import json
import os
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
    timeout_seconds: float = 90.0

    @classmethod
    def from_env(cls) -> "QiniuSettings":
        timeout = os.getenv("QINIU_AI_TIMEOUT_SECONDS", "90")
        try:
            timeout_seconds = max(1.0, min(float(timeout), 300.0))
        except ValueError:
            timeout_seconds = 90.0
        return cls(
            api_key=os.getenv("QINIU_AI_API_KEY", "").strip(),
            model=os.getenv("QINIU_AI_MODEL", "").strip(),
            base_url=os.getenv("QINIU_AI_BASE_URL", DEFAULT_QINIU_BASE_URL).strip().rstrip("/"),
            timeout_seconds=timeout_seconds,
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

        payload = {
            "model": self.settings.model,
            "messages": messages,
            "stream": False,
            "temperature": 0.2,
            "max_tokens": 6_000,
            "response_format": {"type": "json_object"},
        }
        client = self._http_client or httpx.Client(timeout=self.settings.timeout_seconds)
        should_close = self._http_client is None
        try:
            response = client.post(
                f"{self.settings.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                json=payload,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise QiniuAIError("qiniu_provider_timeout", "七牛 AI 请求超时。") from exc
        except httpx.HTTPStatusError as exc:
            raise QiniuAIError(
                "qiniu_provider_http_error",
                f"七牛 AI 返回 HTTP {exc.response.status_code}。",
            ) from exc
        except httpx.HTTPError as exc:
            raise QiniuAIError("qiniu_provider_connection_error", "无法连接七牛 AI。") from exc
        finally:
            if should_close:
                client.close()

        try:
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise QiniuAIError(
                "qiniu_provider_invalid_response",
                "七牛 AI 未返回可解析的 JSON 对象。",
            ) from exc
        if not isinstance(parsed, dict):
            raise QiniuAIError(
                "qiniu_provider_invalid_response",
                "七牛 AI 返回的 JSON 根节点必须是对象。",
            )
        return parsed

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
