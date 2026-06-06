import type { GenerationResponse, ParseResponse } from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  payload: Record<string, unknown> | null;

  constructor(message: string, payload: Record<string, unknown> | null = null) {
    super(message);
    this.name = "ApiError";
    this.payload = payload;
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("无法连接后端服务。请确认 API 已启动并检查前端 API 地址配置。");
  }

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.message ?? payload?.detail ?? `请求失败（HTTP ${response.status}）`;
    throw new ApiError(detail, payload);
  }
  return payload as T;
}

export const parseNovel = (novelText: string) =>
  post<ParseResponse>("/api/v1/projects/parse", { novel_text: novelText });

export const generateLocal = (novelText: string, title: string) =>
  post<GenerationResponse>("/api/v1/projects/generate-local", {
    novel_text: novelText,
    title,
  });
