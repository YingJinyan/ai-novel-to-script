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
  configured: false,
  model: "",
  base_url: "https://api.qnaigc.com/v1",
  mode: "qiniu_ai",
};

function mockApi(
  projectResponses: Array<Response | Error>,
  status = qiniuStatus,
) {
  let index = 0;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (String(input).includes("/providers/qiniu/status")) {
      return new Response(JSON.stringify(status), { status: 200 });
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
    fireEvent.click(screen.getByRole("button", { name: "生成结构化剧本" }));

    await screen.findByText("来源证据");
    expect(screen.getByText("“甲”")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /质量门禁/ }));
    expect(screen.getByText("质量门禁通过")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.getByText("0", { selector: ".metric-row strong" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "原始 YAML" }));
    expect(screen.getByText(/schema_version: 1.0.0/)).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "生成结构化剧本" }));

    await screen.findByText("质量门禁阻断");
    expect(screen.getByText("证据与原文不匹配。")).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "生成结构化剧本" }));
    await screen.findByRole("button", { name: "下载剧本 YAML" });
    fireEvent.click(screen.getByRole("button", { name: "生成结构化剧本" }));

    await screen.findByText("质量门禁阻断");
    expect(screen.queryByRole("button", { name: "下载剧本 YAML" })).not.toBeInTheDocument();
  });

  it("enables Qiniu AI only when the backend reports a configured provider", async () => {
    const fetchMock = mockApi(
      [
        new Response(JSON.stringify(parsePayload), { status: 200 }),
        new Response(JSON.stringify(generationPayload), { status: 200 }),
      ],
      { ...qiniuStatus, configured: true, model: "configured-model" },
    );
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    fireEvent.click(await screen.findByRole("button", { name: /七牛 AI configured-model/ }));
    fireEvent.click(screen.getByRole("button", { name: "使用七牛 AI 润色" }));

    await screen.findByText("来源证据");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/projects/generate-ai",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("clears an existing result when the generation mode changes", async () => {
    mockApi(
      [
        new Response(JSON.stringify(parsePayload), { status: 200 }),
        new Response(JSON.stringify(generationPayload), { status: 200 }),
      ],
      { ...qiniuStatus, configured: true, model: "configured-model" },
    );
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "解析并检查" }));
    await screen.findByText("可以生成");
    fireEvent.click(screen.getByRole("button", { name: "生成结构化剧本" }));
    await screen.findByRole("button", { name: "下载剧本 YAML" });
    fireEvent.click(screen.getByRole("button", { name: /七牛 AI configured-model/ }));

    expect(screen.queryByRole("button", { name: "下载剧本 YAML" })).not.toBeInTheDocument();
    expect(screen.getByText("七牛 AI 受限润色模式")).toBeInTheDocument();
  });
});
