import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const parsePayload = {
  eligible: true,
  chapters: [
    { id: "chapter_001", order: 1, title: "第一章", text: "甲" },
    { id: "chapter_002", order: 2, title: "第二章", text: "乙" },
    { id: "chapter_003", order: 3, title: "第三章", text: "丙" },
  ],
  preamble: "",
  total_characters: 30,
  issues: [],
};

const generationPayload = {
  screenplay: {
    schema_version: "1.0.0",
    project: { title: "雨夜来信", logline: "一封旧信带来真相。" },
    source: {
      chapter_count: 3,
      total_characters: 30,
      chapters: parsePayload.chapters.map((chapter) => ({
        ...chapter,
        summary: chapter.text,
        content_sha256: "a".repeat(64),
      })),
    },
    story_bible: { locations: [{ id: "location_001", name: "未指定场景" }], characters: [] },
    narrative_events: [
      {
        id: "event_001",
        chapter_id: "chapter_001",
        summary: "甲",
        importance: "major",
        evidence: { quote: "甲", start_char: 0, end_char: 1 },
      },
    ],
    screenplay: {
      synopsis: "一封旧信带来真相。",
      scenes: [
        {
          id: "scene_001",
          order: 1,
          heading: { int_ext: "INT_EXT", location_id: "location_001", time_of_day: "未指定" },
          purpose: "保留第一章事件。",
          character_ids: [],
          beats: [{ type: "action", text: "甲" }],
          traceability: {
            origin: "source_adaptation",
            source_chapter_ids: ["chapter_001"],
            source_event_ids: ["event_001"],
            adaptation_actions: [{ type: "rewrite", description: "改写", rationale: "形成场次" }],
          },
        },
      ],
    },
  },
  source_texts: { chapter_001: "甲", chapter_002: "乙", chapter_003: "丙" },
  issues: [],
  quality_report: { passed: true, metrics: { chapter_coverage: 1, target_scene_delta: 0 }, issues: [] },
};

const qiniuStatus = {
  provider: "qiniu-ai",
  credentials_configured: false,
  configured: false,
  model: "",
  base_url: "https://api.qnaigc.com/v1",
  mode: "qiniu_ai",
};

function mockApi(
  projectResponses: Array<Response | Error | Promise<Response>>,
  status = qiniuStatus,
  models: string[] = [],
) {
  let index = 0;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (String(input).includes("/providers/qiniu/status")) {
      return new Response(JSON.stringify(status), { status: 200 });
    }
    if (String(input).includes("/providers/qiniu/models")) {
      return new Response(JSON.stringify({
        provider: "qiniu-ai",
        selected_model: status.model,
        models,
      }), { status: 200 });
    }
    const response = projectResponses[index++];
    if (response instanceof Error) throw response;
    if (!response) throw new Error("Unexpected API request");
    return response;
  });
}

describe("workbench", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("calls parse API and displays real chapter result", async () => {
    const fetchMock = mockApi([
      new Response(JSON.stringify(parsePayload), { status: 200 }),
    ]);
    render(<App />);
    fireEvent.change(screen.getByLabelText("小说原文"), { target: { value: "第一章\n甲\n第二章\n乙\n第三章\n丙" } });
    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));

    await screen.findByText("可以生成");
    expect(screen.getByText("第三章")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/projects/parse", expect.objectContaining({ method: "POST" }));
  });

  it("shows a clear backend connection error", async () => {
    mockApi([new TypeError("offline")]);
    render(<App />);
    fireEvent.change(screen.getByLabelText("小说原文"), { target: { value: "novel" } });
    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("无法连接后端服务"));
  });

  it("generates a traceable screenplay and exposes quality and YAML views", async () => {
    mockApi([
      new Response(JSON.stringify(parsePayload), { status: 200 }),
      new Response(JSON.stringify(generationPayload), { status: 200 }),
    ]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    expect(screen.getByText("当前将使用可靠兜底")).toBeInTheDocument();
    expect(screen.queryByText(/本地规则模式不猜测人物身份/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "使用可靠兜底生成骨架" }));

    await screen.findByText("来源证据");
    expect(screen.getByText("可靠兜底骨架")).toBeInTheDocument();
    expect(screen.getByText("“甲”")).toBeInTheDocument();
    expect(screen.getByText("检查 AI 识别的人物、目标和地点是否准确。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /交付检查/ }));
    expect(screen.getByText("交付检查通过")).toBeInTheDocument();
    expect(screen.getByText("章节覆盖率")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.getByText("0", { selector: ".metric-row strong" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "原始 YAML" }));
    expect((screen.getByLabelText("可编辑剧本 YAML") as HTMLTextAreaElement).value)
      .toContain("schema_version: 1.0.0");
  });

  it("shows quality gate diagnostics returned by the backend", async () => {
    const blockedReport = {
      passed: false,
      metrics: { source_traceability_coverage: 0 },
      issues: [{
        code: "evidence_validation_error",
        severity: "error",
        message: "证据与原文不匹配。",
        related_ids: ["event_001"],
      }],
    };
    mockApi([
      new Response(JSON.stringify(parsePayload), { status: 200 }),
      new Response(JSON.stringify({
        code: "generated_screenplay_failed_quality_gate",
        message: "生成结果未通过质量门禁。",
        related_ids: [],
        quality_report: blockedReport,
      }), { status: 500 }),
    ]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    fireEvent.click(screen.getByRole("button", { name: "使用可靠兜底生成骨架" }));

    await screen.findByText("质量门禁阻断");
    expect(screen.getByText("证据与原文不匹配。")).toBeInTheDocument();
  });

  it("shows actionable generation diagnostics with scene and plot context", async () => {
    mockApi([
      new Response(JSON.stringify(parsePayload), { status: 200 }),
      new Response(JSON.stringify({
        code: "qiniu_provider_output_invalid",
        message: "七牛 AI 自动修复后仍未通过完整结构校验。",
        related_ids: [],
        diagnostics: [{
          code: "ai_character_reference_ambiguous",
          severity: "error",
          message: "场次 5 的人物称谓 Guide 存在歧义；关联剧情：穿过尸洞。",
          related_ids: ["scene_005"],
        }],
      }), { status: 502 }),
    ]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    fireEvent.click(screen.getByRole("button", { name: "使用可靠兜底生成骨架" }));

    await screen.findByText("问题定位与处理建议");
    expect(screen.getByText(/场次 5 的人物称谓 Guide/)).toBeInTheDocument();
    expect(screen.getByText(/通常无需修改原小说/)).toBeInTheDocument();
  });

  it("removes an old screenplay before a failed regeneration", async () => {
    mockApi([
      new Response(JSON.stringify(parsePayload), { status: 200 }),
      new Response(JSON.stringify(generationPayload), { status: 200 }),
      new Response(JSON.stringify({
        code: "generated_screenplay_failed_quality_gate",
        message: "生成结果未通过质量门禁。",
        related_ids: [],
        quality_report: { passed: false, metrics: {}, issues: [] },
      }), { status: 500 }),
    ]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    fireEvent.click(screen.getByRole("button", { name: "使用可靠兜底生成骨架" }));
    await screen.findByRole("button", { name: "下载已通过剧本 YAML" });
    fireEvent.click(screen.getByRole("button", { name: "使用可靠兜底生成骨架" }));

    await screen.findByText("质量门禁阻断");
    expect(screen.queryByRole("button", { name: "下载已通过剧本 YAML" })).not.toBeInTheDocument();
  });

  it("enables Qiniu AI only when the backend reports a configured provider", async () => {
    const fetchMock = mockApi(
      [
        new Response(JSON.stringify(parsePayload), { status: 200 }),
        new Response(JSON.stringify(generationPayload), { status: 200 }),
      ],
      { ...qiniuStatus, credentials_configured: true, configured: true, model: "configured-model" },
      ["configured-model", "second-model"],
    );
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    const aiMode = await screen.findByRole("button", { name: /七牛 AI · 完整剧本化/ });
    expect(aiMode).toHaveClass("selected");
    expect(screen.getByText("当前将使用七牛 AI 完整剧本化")).toBeInTheDocument();
    expect(screen.getByText(/AI 会尝试识别人物与说话人/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "使用七牛 AI 生成完整剧本" }));

    await screen.findByText("来源证据");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/projects/generate-ai",
      expect.objectContaining({ method: "POST" }),
    );
    const aiRequest = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/projects/generate-ai")
    );
    expect(JSON.parse(String(aiRequest?.[1]?.body))).toMatchObject({
      model: "configured-model",
    });
  });

  it("clears an existing result when the generation mode changes", async () => {
    mockApi(
      [
        new Response(JSON.stringify(parsePayload), { status: 200 }),
        new Response(JSON.stringify(generationPayload), { status: 200 }),
      ],
      { ...qiniuStatus, credentials_configured: true, configured: true, model: "configured-model" },
      ["configured-model"],
    );
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    fireEvent.click(screen.getByRole("button", { name: /可靠兜底/ }));
    fireEvent.click(screen.getByRole("button", { name: "使用可靠兜底生成骨架" }));
    await screen.findByRole("button", { name: "下载已通过剧本 YAML" });
    const aiMode = screen.getByRole("button", { name: /七牛 AI · 完整剧本化/ });
    fireEvent.click(aiMode);

    expect(screen.queryByRole("button", { name: "下载已通过剧本 YAML" })).not.toBeInTheDocument();
    expect(aiMode).toHaveClass("selected");
  });

  it("prefers a recommended text model when the configured default is unavailable", async () => {
    mockApi(
      [new Response(JSON.stringify(parsePayload), { status: 200 })],
      { ...qiniuStatus, credentials_configured: true, configured: true, model: "invalid-project-name" },
      ["qwen2.5-vl-7b-instruct", "deepseek-v3", "deepseek-r1"],
    );
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    const modelSelect = await screen.findByLabelText("七牛模型");
    await waitFor(() => expect(modelSelect).toHaveValue("deepseek-v3"));
    expect(screen.getByText(/推荐：适合结构化文本改编与稳定演示/)).toBeInTheDocument();
  });

  it("avoids a slow configured model and explains the slow-model risk", async () => {
    mockApi(
      [new Response(JSON.stringify(parsePayload), { status: 200 })],
      { ...qiniuStatus, credentials_configured: true, configured: true, model: "deepseek-v3.1" },
      ["deepseek-v3.1", "deepseek-v3"],
    );
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    const modelSelect = await screen.findByLabelText("七牛模型");
    await waitFor(() => expect(modelSelect).toHaveValue("deepseek-v3"));
    fireEvent.change(modelSelect, { target: { value: "deepseek-v3.1" } });

    expect(screen.getByText(/实测可能等待较久并发生连接中断/)).toBeInTheDocument();
  });

  it("shows elapsed generation progress while waiting for Qiniu", async () => {
    const delayedGeneration = new Promise<Response>(() => {});
    mockApi(
      [
        new Response(JSON.stringify(parsePayload), { status: 200 }),
        delayedGeneration,
      ],
      { ...qiniuStatus, credentials_configured: true, configured: true, model: "deepseek-v3" },
      ["deepseek-v3"],
    );
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    fireEvent.click(screen.getByRole("button", { name: "使用七牛 AI 生成完整剧本" }));

    expect(await screen.findByRole("status")).toHaveTextContent("七牛 AI 正在生成");
    expect(screen.getByRole("status")).toHaveTextContent("正在提交小说与证据单元");
  });

  it("explains extracted story elements and fallback limitations", async () => {
    mockApi([
      new Response(JSON.stringify(parsePayload), { status: 200 }),
      new Response(JSON.stringify(generationPayload), { status: 200 }),
    ]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    fireEvent.click(screen.getByRole("button", { name: "使用可靠兜底生成骨架" }));
    await screen.findByText("来源证据");
    fireEvent.click(screen.getByRole("button", { name: /故事要素/ }));

    expect(screen.getByText(/这里为空或只有“未指定场景”/)).toBeInTheDocument();
    expect(screen.getByText("当前结果没有识别人物。")).toBeInTheDocument();
    expect(screen.getByText("未指定场景")).toBeInTheDocument();
  });

  it("sends edited YAML to the backend and displays a blocking report", async () => {
    const blockedReport = {
      passed: false,
      metrics: {},
      issues: [{
        code: "schema_validation_error",
        severity: "error",
        message: "project is required.",
        related_ids: [],
      }],
    };
    const fetchMock = mockApi([
      new Response(JSON.stringify(parsePayload), { status: 200 }),
      new Response(JSON.stringify(generationPayload), { status: 200 }),
      new Response(JSON.stringify(blockedReport), { status: 200 }),
    ]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    fireEvent.click(screen.getByRole("button", { name: "使用可靠兜底生成骨架" }));
    await screen.findByText("来源证据");
    fireEvent.click(screen.getByRole("button", { name: "原始 YAML" }));
    fireEvent.change(screen.getByLabelText("可编辑剧本 YAML"), {
      target: { value: "schema_version: 1.0.0\n" },
    });
    expect(screen.getByRole("button", { name: "下载已通过剧本 YAML" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下载已通过版本" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "重新校验 YAML" }));

    await screen.findByText("当前 YAML 被质量门禁阻断，请查看问题。");
    expect(screen.getByRole("button", { name: "下载已通过剧本 YAML" })).toBeDisabled();
    expect(screen.getByText("project is required.")).toBeInTheDocument();
    const validationRequest = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/api/v1/validate")
    );
    expect(JSON.parse(String(validationRequest?.[1]?.body))).toMatchObject({
      screenplay: { schema_version: "1.0.0" },
      source_texts: generationPayload.source_texts,
    });
  });

  it("ignores an outdated passing validation response after the YAML changes", async () => {
    let resolveValidation!: (response: Response) => void;
    const delayedValidation = new Promise<Response>((resolve) => {
      resolveValidation = resolve;
    });
    mockApi([
      new Response(JSON.stringify(parsePayload), { status: 200 }),
      new Response(JSON.stringify(generationPayload), { status: 200 }),
      delayedValidation,
    ]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    fireEvent.click(screen.getByRole("button", { name: "使用可靠兜底生成骨架" }));
    await screen.findByText("来源证据");
    fireEvent.click(screen.getByRole("button", { name: "原始 YAML" }));
    fireEvent.click(screen.getByRole("button", { name: "重新校验 YAML" }));
    fireEvent.change(screen.getByLabelText("可编辑剧本 YAML"), {
      target: { value: "schema_version: 1.0.0\n" },
    });
    resolveValidation(
      new Response(JSON.stringify(generationPayload.quality_report), { status: 200 }),
    );

    await screen.findByText("校验期间 YAML 已修改，请重新校验。");
    expect(screen.getByRole("button", { name: "下载已通过剧本 YAML" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下载已通过版本" })).toBeDisabled();
  });
});
