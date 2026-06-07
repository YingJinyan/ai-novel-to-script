import { useEffect, useMemo, useRef, useState } from "react";
import yaml from "js-yaml";
import { ApiError, generateAI, generateLocal, getQiniuModels, getQiniuStatus, getScreenplaySchema, parseNovel, validateScreenplay } from "./api";
import type { GenerationResponse, Issue, ParseResponse, QualityReport, Scene } from "./types";
import { buildValidationBundle } from "./validationBundle";

type ResultTab = "script" | "bible" | "coverage" | "quality" | "yaml";
type GenerationMode = "local" | "qiniu";
type SceneDensity = "concise" | "balanced" | "detailed";
type ModelGroup = "recommended" | "general" | "slow" | "thinking" | "vision";

const issueLabel = { error: "阻断", warning: "注意", info: "信息" };
const roleLabel: Record<string, string> = {
  protagonist: "主角",
  antagonist: "对手",
  supporting: "配角",
  minor: "次要人物",
};
const SAMPLE_NOVEL = `第一章 雨夜车站
林夏在雨夜抵达车站，发现长椅下压着一封写给自己的旧信。

第二章 未寄出的信
旧信提醒林夏，父亲离开前曾把真相藏在站长室的时刻表后。

第三章 天亮之前
林夏找到时刻表后的录音。天亮时，她决定公开真相，也原谅了迟到的告别。`;

function IssueList({ issues, empty = "未发现问题" }: { issues: Issue[]; empty?: string }) {
  if (!issues.length) return <div className="clean-state"><span>✓</span>{empty}</div>;
  return (
    <div className="issue-list">
      {issues.map((issue, index) => (
        <div className={`issue ${issue.severity}`} key={`${issue.code}-${index}`}>
          <span className="issue-level">{issueLabel[issue.severity]}</span>
          <div><strong>{issue.message}</strong><code>{issue.code}</code></div>
        </div>
      ))}
    </div>
  );
}

const RATIO_METRICS = new Set([
  "chapter_coverage",
  "event_coverage",
  "critical_event_coverage",
  "must_keep_coverage",
  "source_traceability_coverage",
  "invented_scene_ratio",
]);
const METRIC_LABELS: Record<string, string> = {
  chapter_coverage: "章节覆盖率",
  event_coverage: "事件覆盖率",
  critical_event_coverage: "关键事件覆盖率",
  must_keep_coverage: "必保事件覆盖率",
  source_traceability_coverage: "来源可追溯率",
  invented_scene_ratio: "新增场次比例",
  target_scene_delta: "场次数要求偏差",
};
const RECOMMENDED_QINIU_MODELS = [
  "deepseek-v3",
  "qwen3-max",
  "moonshotai/kimi-k2.5",
];
const SLOW_QINIU_MODELS = [
  "deepseek-v3.1",
  "deepseek/deepseek-v3.1-terminus",
];

function modelGroup(model: string): ModelGroup {
  const normalized = model.toLowerCase();
  if (RECOMMENDED_QINIU_MODELS.includes(model)) return "recommended";
  if (normalized.includes("vl") || normalized.includes("vision")) return "vision";
  if (normalized.includes("thinking") || normalized.includes("reason") || normalized.includes("r1")) {
    return "thinking";
  }
  if (SLOW_QINIU_MODELS.includes(model)) return "slow";
  return "general";
}

function modelGuidance(model: string): string {
  switch (modelGroup(model)) {
    case "recommended": return "推荐：适合结构化文本改编与稳定演示。";
    case "slow": return "慢模型：实测可能等待较久并发生连接中断，不建议演示时使用。";
    case "thinking": return "推理模型：可能更慢，JSON 输出稳定性需实测。";
    case "vision": return "视觉模型：当前任务不需要图片理解，不建议优先选择。";
    default: return "通用文本模型：可用性与输出质量需用真实小说验证。";
  }
}

function groupedModels(models: string[]): Record<ModelGroup, string[]> {
  return models.reduce<Record<ModelGroup, string[]>>(
    (groups, model) => {
      groups[modelGroup(model)].push(model);
      return groups;
    },
    { recommended: [], general: [], slow: [], thinking: [], vision: [] },
  );
}

function Metric({ name, value }: { name: string; value: number }) {
  const isRatio = RATIO_METRICS.has(name);
  const percentage = Math.round(value * 100);
  const label = isRatio ? `${percentage}%` : String(value);
  return (
    <div className="metric">
      <div className="metric-row"><span>{METRIC_LABELS[name] ?? name.replaceAll("_", " ")}</span><strong>{label}</strong></div>
      {isRatio && <div className="meter"><i style={{ width: `${Math.max(0, Math.min(100, percentage))}%` }} /></div>}
    </div>
  );
}

function SceneDetail({ scene, result }: { scene: Scene; result: GenerationResponse }) {
  const locations = result.screenplay.story_bible?.locations ?? [];
  const characters = result.screenplay.story_bible?.characters ?? [];
  const location = locations.find((item) => item.id === scene.heading.location_id)?.name ?? scene.heading.location_id;
  const events = (result.screenplay.narrative_events ?? []).filter((event) =>
    scene.traceability.source_event_ids.includes(event.id),
  );
  const chapters = result.screenplay.source.chapters.filter((chapter) =>
    scene.traceability.source_chapter_ids.includes(chapter.id),
  );

  return (
    <article className="scene-detail">
      <div className="scene-kicker">场次 {String(scene.order).padStart(2, "0")} · {scene.id}</div>
      <h2>{scene.heading.int_ext} · {location} · {scene.heading.time_of_day}</h2>
      <p className="purpose">{scene.purpose}</p>
      <div className="beat-list">
        {scene.beats.map((beat, index) => (
          <div className="beat" key={index}>
            <div className="beat-meta">
              <span>{beat.type}</span>
              {beat.character_id && <strong>{characters.find((item) => item.id === beat.character_id)?.name ?? beat.character_id}</strong>}
              {beat.parenthetical && <small>{beat.parenthetical}</small>}
            </div>
            <p>{beat.text}</p>
          </div>
        ))}
      </div>
      <section className="evidence-panel">
        <div className="section-title"><span>来源证据</span><small>{scene.traceability.origin}</small></div>
        {events.map((event) => (
          <blockquote key={event.id}>
            <p>“{event.evidence.quote}”</p>
            <footer>{event.id} · {event.chapter_id} · 字符 {event.evidence.start_char}–{event.evidence.end_char}</footer>
          </blockquote>
        ))}
        {!events.length && <p className="muted">该场次未关联来源事件。</p>}
        <div className="trace-tags">{chapters.map((chapter) => <span key={chapter.id}>{chapter.title}</span>)}</div>
        {scene.traceability.adaptation_actions.map((action, index) => (
          <div className="adaptation" key={index}><strong>{action.type}</strong><span>{action.description}</span></div>
        ))}
      </section>
    </article>
  );
}

export default function App() {
  const [novelText, setNovelText] = useState(SAMPLE_NOVEL);
  const [title, setTitle] = useState("雨夜来信");
  const [parsed, setParsed] = useState<ParseResponse | null>(null);
  const [result, setResult] = useState<GenerationResponse | null>(null);
  const [selectedScene, setSelectedScene] = useState(0);
  const [tab, setTab] = useState<ResultTab>("script");
  const [loading, setLoading] = useState<"parse" | "generate" | null>(null);
  const [generationSeconds, setGenerationSeconds] = useState(0);
  const [error, setError] = useState("");
  const [errorDiagnostics, setErrorDiagnostics] = useState<Issue[]>([]);
  const [blockedQuality, setBlockedQuality] = useState<QualityReport | null>(null);
  const [generationMode, setGenerationMode] = useState<GenerationMode>("local");
  const [qiniuModels, setQiniuModels] = useState<string[]>([]);
  const [selectedQiniuModel, setSelectedQiniuModel] = useState("");
  const [sceneDensity, setSceneDensity] = useState<SceneDensity>("balanced");
  const [providerMessage, setProviderMessage] = useState("");
  const [providerLoading, setProviderLoading] = useState(false);
  const [yamlDraft, setYamlDraft] = useState("");
  const [yamlReport, setYamlReport] = useState<QualityReport | null>(null);
  const [yamlMessage, setYamlMessage] = useState("");
  const [yamlValidating, setYamlValidating] = useState(false);
  const [yamlDirty, setYamlDirty] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const sourceRevision = useRef(0);
  const yamlRevision = useRef(0);
  const generationModeChosen = useRef(false);

  const scenes = result?.screenplay.screenplay.scenes ?? [];
  const yamlText = useMemo(() => result ? yaml.dump(result.screenplay, { noRefs: true, lineWidth: 100 }) : "", [result]);
  const activeQualityReport = yamlDirty ? null : yamlReport ?? result?.quality_report ?? null;

  useEffect(() => {
    yamlRevision.current += 1;
    setYamlDraft(yamlText);
    setYamlReport(null);
    setYamlMessage("");
    setYamlDirty(false);
  }, [yamlText]);

  useEffect(() => {
    if (loading !== "generate") {
      setGenerationSeconds(0);
      return;
    }
    const timer = window.setInterval(() => setGenerationSeconds((seconds) => seconds + 1), 1000);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function refreshQiniuProvider() {
    setProviderLoading(true);
    setProviderMessage("");
    try {
      const status = await getQiniuStatus();
      setSelectedQiniuModel(status.model);
      if (!status.credentials_configured) {
        setQiniuModels([]);
        setProviderMessage("后端尚未配置七牛 API Key。");
        return;
      }
      const response = await getQiniuModels();
      setQiniuModels(response.models);
      const configuredIsStable = response.models.includes(response.selected_model)
        && !["slow", "thinking", "vision"].includes(modelGroup(response.selected_model));
      const preferred = configuredIsStable
        ? response.selected_model
        : RECOMMENDED_QINIU_MODELS.find((model) => response.models.includes(model))
          ?? response.models.find((model) => modelGroup(model) === "general")
          ?? response.models[0]
          ?? "";
      setSelectedQiniuModel(preferred);
      if (preferred && !generationModeChosen.current) {
        setGenerationMode("qiniu");
      }
      setProviderMessage(`已从七牛读取 ${response.models.length} 个可用模型。`);
    } catch (err) {
      setQiniuModels([]);
      setProviderMessage(err instanceof Error ? err.message : "七牛模型列表读取失败。");
    } finally {
      setProviderLoading(false);
    }
  }

  useEffect(() => {
    void refreshQiniuProvider();
  }, []);

  async function handleParse() {
    if (!novelText.trim()) return setError("请先粘贴或导入小说正文。");
    setLoading("parse"); setError(""); setErrorDiagnostics([]); setBlockedQuality(null); setResult(null);
    try {
      setParsed(await parseNovel(novelText));
    } catch (err) {
      setParsed(null); setError(err instanceof Error ? err.message : "解析请求失败。");
      setErrorDiagnostics(err instanceof ApiError ? (err.payload?.diagnostics as Issue[] | undefined) ?? [] : []);
    } finally { setLoading(null); }
  }

  async function handleGenerate() {
    if (!title.trim()) return setError("请填写项目名称。");
    if (!parsed?.eligible) return setError("当前解析结果未达到生成条件，请先处理阻断问题。");
    if (generationMode === "qiniu" && !selectedQiniuModel) {
      return setError("七牛 AI 尚无可用模型，请刷新模型列表或使用可靠兜底模式。");
    }
    setLoading("generate"); setError(""); setErrorDiagnostics([]); setBlockedQuality(null); setResult(null);
    const requestedRevision = sourceRevision.current;
    try {
      const generated = generationMode === "qiniu"
        ? await generateAI(novelText, title.trim(), selectedQiniuModel, sceneDensity)
        : await generateLocal(novelText, title.trim());
      if (requestedRevision === sourceRevision.current) {
        setResult(generated); setSelectedScene(0); setTab("script");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成请求失败。");
      setErrorDiagnostics(err instanceof ApiError ? (err.payload?.diagnostics as Issue[] | undefined) ?? [] : []);
      if (err instanceof ApiError && err.payload?.quality_report) {
        setBlockedQuality(err.payload.quality_report as QualityReport);
      }
    } finally { setLoading(null); }
  }

  async function importFile(file?: File) {
    if (!file) return;
    sourceRevision.current += 1;
    const importedText = await file.text();
    sourceRevision.current += 1;
    setNovelText(importedText); setParsed(null); setResult(null); setBlockedQuality(null); setError(""); setErrorDiagnostics([]);
  }

  function loadSample() {
    sourceRevision.current += 1;
    setNovelText(SAMPLE_NOVEL);
    setTitle("雨夜来信");
    setParsed(null);
    setResult(null);
    setBlockedQuality(null);
    setError("");
    setErrorDiagnostics([]);
  }

  function selectGenerationMode(mode: GenerationMode) {
    generationModeChosen.current = true;
    setGenerationMode(mode);
    setResult(null);
    setBlockedQuality(null);
    setError("");
    setErrorDiagnostics([]);
  }

  function downloadYaml() {
    if (!activeQualityReport?.passed) return;
    const url = URL.createObjectURL(new Blob([yamlDraft || yamlText], { type: "text/yaml;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url; link.download = `${title.trim() || "screenplay"}.yaml`; link.click();
    URL.revokeObjectURL(url);
  }

  async function downloadSchema() {
    try {
      const schema = await getScreenplaySchema();
      const content = JSON.stringify(schema, null, 2);
      const url = URL.createObjectURL(new Blob([content], { type: "application/schema+json;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url; link.download = "screenplay.schema.json"; link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法下载 YAML Schema。");
    }
  }

  async function validateYamlDraft() {
    if (!result) return;
    const requestedRevision = yamlRevision.current;
    setYamlValidating(true);
    setYamlMessage("");
    try {
      const parsed = yaml.load(yamlDraft);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setYamlReport({
          passed: false,
          metrics: {},
          issues: [{ code: "yaml_parse_error", severity: "error", message: "YAML 根节点必须是对象。", related_ids: [] }],
        });
        setYamlMessage("YAML 根节点必须是对象。");
        setYamlDirty(false);
        return;
      }
      const report = await validateScreenplay(parsed, result.source_texts);
      if (requestedRevision !== yamlRevision.current) {
        setYamlMessage("校验期间 YAML 已修改，请重新校验。");
        return;
      }
      setYamlReport(report);
      setYamlDirty(false);
      setYamlMessage(report.passed ? "当前 YAML 已通过质量门禁。" : "当前 YAML 被质量门禁阻断，请查看问题。");
      if (report.passed) {
        setResult((current) => current ? {
          ...current,
          screenplay: parsed as GenerationResponse["screenplay"],
          quality_report: report,
        } : current);
      }
    } catch (err) {
      if (requestedRevision !== yamlRevision.current) {
        setYamlMessage("校验期间 YAML 已修改，请重新校验。");
        return;
      }
      const message = err instanceof Error ? `YAML 无法解析：${err.message}` : "YAML 无法解析。";
      setYamlReport({
        passed: false,
        metrics: {},
        issues: [{ code: "yaml_parse_error", severity: "error", message, related_ids: [] }],
      });
      setYamlMessage(message);
      setYamlDirty(false);
    } finally {
      setYamlValidating(false);
    }
  }

  function downloadValidationBundle() {
    if (!result) return;
    const content = JSON.stringify(buildValidationBundle(result), null, 2);
    const url = URL.createObjectURL(new Blob([content], { type: "application/json;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url; link.download = `${title.trim() || "screenplay"}.validation.json`; link.click();
    URL.revokeObjectURL(url);
  }

  const eventCoverage = result?.screenplay.narrative_events.map((event) => {
    const chapter = result.screenplay.source.chapters.find((item) => item.id === event.chapter_id);
    const linkedScenes = scenes.filter((scene) => scene.traceability.source_event_ids.includes(event.id));
    return { chapter, event, linkedScenes };
  }) ?? [];
  const qiniuModelGroups = groupedModels(qiniuModels);
  const resultGeneration = result?.screenplay.project.generation;
  const resultModeLabel = resultGeneration?.mode === "qiniu_ai"
    ? `七牛 AI 完整改编 · ${resultGeneration.model}`
    : "可靠兜底骨架";
  const resultCounts = result
    ? `${result.screenplay.story_bible.characters.length} 人物 · ${result.screenplay.story_bible.locations.length} 地点 · ${result.screenplay.narrative_events.length} 事件 · ${scenes.length} 场次`
    : "";
  const characters = result?.screenplay.story_bible.characters ?? [];
  const locations = result?.screenplay.story_bible.locations ?? [];
  const generationProgress = generationSeconds < 20
    ? "正在提交小说与证据单元。"
    : generationSeconds < 60
      ? "正在提取人物、地点与关键事件。"
      : generationSeconds < 120
        ? "正在生成场次、对白并执行结构校验。"
        : "当前模型响应较慢。请继续等待；若失败，请改用 deepseek-v3 或 qwen3-max。";

  return (
    <div className="app-shell">
      <header>
        <div className="brand"><span className="brand-mark">溯</span><div><strong>溯源剧本工作台</strong><small>可信 · 可控 · 可追溯</small></div></div>
        <div className="mode"><i />证据链与质量门禁已启用</div>
      </header>

      <main>
        <section className="intro">
          <div><p className="eyebrow">NOVEL → SCREENPLAY</p><h1>让 AI 改编的每一个场次，都有出处。</h1><p>导入至少 3 章小说，自动提取人物、地点与事件，生成可验证、可编辑的结构化剧本。</p></div>
          <div className="steps"><span className={parsed ? "done" : "active"}>01 输入检查</span><span className={result ? "done" : parsed?.eligible ? "active" : ""}>02 AI 剧本化</span><span className={result ? "active" : ""}>03 溯源审阅</span></div>
        </section>

        <section className="import-grid">
          <div className="panel source-panel">
            <div className="panel-head"><div><span className="panel-number">01</span><h2>小说原文</h2></div><div className="panel-actions"><button className="text-button" disabled={!!loading} onClick={loadSample}>加载演示小说</button><button className="text-button" disabled={!!loading} onClick={() => fileInput.current?.click()}>导入 .txt</button></div></div>
            <input ref={fileInput} type="file" accept=".txt,text/plain" hidden disabled={!!loading} onChange={(e) => importFile(e.target.files?.[0])} />
            <textarea aria-label="小说原文" disabled={!!loading} value={novelText} onChange={(e) => { sourceRevision.current += 1; setNovelText(e.target.value); setParsed(null); setResult(null); setBlockedQuality(null); }} placeholder={"粘贴小说正文，章节标题示例：\n\n第一章 雨夜\n正文……\n\n第二章 来信\n正文……\n\n第三章 真相\n正文……"} />
            <div className="source-footer"><span>{novelText.length.toLocaleString()} / 100,000 字符</span><button className="primary" disabled={!!loading} onClick={handleParse}>{loading === "parse" ? "正在解析…" : "解析并检查"}</button></div>
          </div>

          <div className="panel parse-panel">
            <div className="panel-head"><div><span className="panel-number">02</span><h2>输入检查</h2></div>{parsed && <span className={`status ${parsed.eligible ? "pass" : "block"}`}>{parsed.eligible ? "可以生成" : "存在阻断"}</span>}</div>
            {!parsed ? <div className="empty"><div className="empty-icon">⌁</div><strong>等待解析结果</strong><p>章节、字符统计和输入问题将在这里显示。</p></div> : <>
              <div className="stats"><div><strong>{parsed.chapters.length}</strong><span>识别章节</span></div><div><strong>{parsed.total_characters.toLocaleString()}</strong><span>总字符</span></div><div><strong>{parsed.issues.length}</strong><span>问题</span></div></div>
              <div className="chapter-strip">{parsed.chapters.map((chapter) => <div key={chapter.id}><span>{String(chapter.order).padStart(2, "0")}</span><strong>{chapter.title}</strong><small>{chapter.text.length} 字符</small></div>)}</div>
              <IssueList issues={parsed.issues} />
              <div className="provider-picker"><button className={generationMode === "qiniu" ? "selected" : ""} disabled={!!loading || !selectedQiniuModel} onClick={() => selectGenerationMode("qiniu")}><strong>七牛 AI · 完整剧本化</strong><span>{selectedQiniuModel ? `${selectedQiniuModel} · 人物、地点、事件、场次与对白` : "未读取到可用模型"}</span></button><button className={generationMode === "local" ? "selected" : ""} disabled={!!loading} onClick={() => selectGenerationMode("local")}><strong>可靠兜底</strong><span>不调用 AI，只生成可追溯骨架且不冒充 AI</span></button></div>
              <div className="mode-guidance">{generationMode === "qiniu" ? <><strong>当前将使用七牛 AI 完整剧本化</strong><span>上方对白提示只是输入复核项；AI 会尝试识别人物与说话人，生成后请在“故事要素”中确认。</span></> : <><strong>当前将使用可靠兜底</strong><span>该模式不会推断人物或说话人，只生成可追溯骨架。</span></>}</div>
              <div className="model-picker"><label>七牛模型<select disabled={!!loading || providerLoading || !qiniuModels.length} value={selectedQiniuModel} onChange={(event) => { setSelectedQiniuModel(event.target.value); if (generationMode === "qiniu") setResult(null); }}>{qiniuModels.length ? <><optgroup label="推荐用于小说改编">{qiniuModelGroups.recommended.map((model) => <option value={model} key={model}>{model}</option>)}</optgroup><optgroup label="通用文本模型">{qiniuModelGroups.general.map((model) => <option value={model} key={model}>{model}</option>)}</optgroup><optgroup label="慢模型（不建议演示）">{qiniuModelGroups.slow.map((model) => <option value={model} key={model}>{model}</option>)}</optgroup><optgroup label="推理模型（可能较慢）">{qiniuModelGroups.thinking.map((model) => <option value={model} key={model}>{model}</option>)}</optgroup><optgroup label="视觉模型（当前任务不推荐）">{qiniuModelGroups.vision.map((model) => <option value={model} key={model}>{model}</option>)}</optgroup></> : <option value="">暂无可用模型</option>}</select></label><button className="text-button" disabled={providerLoading || !!loading} onClick={() => void refreshQiniuProvider()}>{providerLoading ? "读取中…" : "刷新七牛模型"}</button><span>{providerMessage} {selectedQiniuModel && modelGuidance(selectedQiniuModel)}</span></div>
              <div className="generate-box"><label>项目名称<input disabled={!!loading} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：雨夜来信" /></label>{generationMode === "qiniu" && <label>改编详略<select aria-label="改编详略" disabled={!!loading} value={sceneDensity} onChange={(event) => { setSceneDensity(event.target.value as SceneDensity); setResult(null); }}><option value="concise">精炼 · 3-5 场</option><option value="balanced">均衡 · 5-9 场</option><option value="detailed">详细 · 8-15 场</option></select></label>}<button className="primary generate" disabled={!parsed.eligible || !!loading} onClick={handleGenerate}>{loading === "generate" ? `正在生成 · ${generationSeconds} 秒` : generationMode === "qiniu" ? "使用七牛 AI 生成完整剧本" : "使用可靠兜底生成骨架"}</button></div>
            </>}
          </div>
        </section>

        {loading === "generate" && <div role="status" className="generation-progress"><strong>{generationMode === "qiniu" ? `七牛 AI 正在生成 · ${generationSeconds} 秒` : "可靠兜底正在生成"}</strong><span>{generationMode === "qiniu" ? generationProgress : "正在构建可追溯骨架。"}</span></div>}
        {error && <><div role="alert" className="error-banner"><strong>请求未完成</strong><span>{error}</span></div>{errorDiagnostics.length > 0 && <section className="generation-diagnostics panel"><div className="section-intro"><h2>问题定位与处理建议</h2><p>以下信息来自本次生成结果，用于定位具体场次、人物、剧情或结构字段；通常无需修改原小说。</p></div><IssueList issues={errorDiagnostics} /></section>}</>}
        {blockedQuality && <section className="blocked-quality panel"><div className="gate block"><span>!</span><div><strong>质量门禁阻断</strong><p>后端拒绝返回未通过校验的生成结果，以下为真实诊断。</p></div></div><div className="metric-grid">{Object.entries(blockedQuality.metrics).map(([name, value]) => <Metric name={name} value={value} key={name} />)}</div><IssueList issues={blockedQuality.issues} /></section>}

        <section className="workspace panel">
          <div className="workspace-head"><div><span className="panel-number">03</span><div><h2>剧本审阅工作台</h2><p>{result ? result.screenplay.project.title : "生成后可审阅场次、证据与质量门禁"}</p>{result && <div className="result-provenance"><strong>{resultModeLabel}</strong><span>{resultCounts}</span></div>}</div></div><div className="download-actions"><button className="download secondary" onClick={() => void downloadSchema()}>下载 YAML Schema</button>{result && <><button className="download secondary" onClick={downloadValidationBundle}>下载验证包</button><button className="download" disabled={!activeQualityReport?.passed} onClick={downloadYaml}>下载已通过剧本 YAML</button></>}</div></div>
          {!result ? <div className="workspace-empty"><span>SCREENPLAY / TRACE / QUALITY</span><h2>尚未生成剧本</h2><p>完成输入检查并生成后，工作台将展示真实接口返回的数据。</p></div> : <>
            <div className="result-guide"><div><strong>场次与证据</strong><span>阅读剧本，并查看每场依据的原文摘录。</span></div><div><strong>故事要素</strong><span>检查 AI 识别的人物、目标和地点是否准确。</span></div><div><strong>事件覆盖</strong><span>确认三章关键情节没有在改编中遗漏。</span></div><div><strong>交付检查</strong><span>确认 YAML、证据链和覆盖率达到下载条件。</span></div></div>
            <nav className="tabs" aria-label="结果视图">
              <button className={tab === "script" ? "active" : ""} onClick={() => setTab("script")}>场次与证据 <b>{scenes.length}</b></button>
              <button className={tab === "bible" ? "active" : ""} onClick={() => setTab("bible")}>故事要素 <b>{characters.length + locations.length}</b></button>
              <button className={tab === "coverage" ? "active" : ""} onClick={() => setTab("coverage")}>事件覆盖 <b>{eventCoverage.length}</b></button>
              <button className={tab === "quality" ? "active" : ""} onClick={() => setTab("quality")}>交付检查 <b className={activeQualityReport ? activeQualityReport.passed ? "good" : "bad" : "pending"}>{activeQualityReport ? activeQualityReport.passed ? "通过" : "阻断" : "待校验"}</b></button>
              <button className={tab === "yaml" ? "active" : ""} onClick={() => setTab("yaml")}>原始 YAML</button>
            </nav>

            {tab === "script" && <div className="script-layout">
              <aside><div className="synopsis"><span>剧本概要</span><p>{result.screenplay.screenplay.synopsis}</p></div>{scenes.map((scene, index) => <button key={scene.id} className={selectedScene === index ? "active" : ""} onClick={() => setSelectedScene(index)}><span>{String(scene.order).padStart(2, "0")}</span><div><strong>{scene.heading.int_ext} · {scene.heading.time_of_day}</strong><small>{scene.purpose}</small></div></button>)}</aside>
              {scenes[selectedScene] && <SceneDetail scene={scenes[selectedScene]} result={result} />}
            </div>}

            {tab === "bible" && <div className="bible-view"><div className="section-intro"><h2>AI 提取的故事要素</h2><p>用于统一人物称呼、人物目标和场景名称。这里为空或只有“未指定场景”，通常说明生成结果仍只是兜底骨架。</p></div>{result.screenplay.story_bible.premise && <div className="premise-card"><span>故事前提</span><p>{result.screenplay.story_bible.premise}</p></div>}<div className="bible-grid"><section><h3>人物 <b>{characters.length}</b></h3>{characters.length ? characters.map((character) => <article className="bible-card" key={character.id}><div><strong>{character.name}</strong><span>{roleLabel[character.role ?? ""] ?? character.role ?? "待确认"}</span></div>{character.aliases?.length ? <small>别名：{character.aliases.join("、")}</small> : null}<p>{character.description || "暂无人物描述"}</p>{character.goal && <footer>目标：{character.goal}</footer>}</article>) : <p className="muted">当前结果没有识别人物。</p>}</section><section><h3>地点 <b>{locations.length}</b></h3>{locations.length ? locations.map((location) => <article className="bible-card" key={location.id}><div><strong>{location.name}</strong><span>{location.id}</span></div><p>{location.description || "暂无地点描述"}</p></article>) : <p className="muted">当前结果没有识别地点。</p>}</section></div></div>}

            {tab === "coverage" && <div className="coverage-view"><div className="section-intro"><h2>事件覆盖</h2><p>事件是 AI 从原文中提取的关键情节；这里检查每个事件是否进入至少一个剧本场次，防止改编时漏掉重要内容。</p></div><div className="coverage-table"><div className="coverage-row head"><span>来源章节</span><span>叙事事件</span><span>关联场次</span><span>状态</span></div>{eventCoverage.map(({ chapter, event, linkedScenes }) => <div className="coverage-row" key={event.id}><span><strong>{chapter?.title ?? event.chapter_id}</strong><small>{event.chapter_id}</small></span><span><strong>{event.id}</strong><small>{event.summary}</small></span><span>{linkedScenes.map((s) => s.id).join(", ") || "—"}</span><span className={linkedScenes.length ? "covered" : "uncovered"}>{linkedScenes.length ? "已覆盖" : "未覆盖"}</span></div>)}</div></div>}

            {tab === "quality" && activeQualityReport && <div className="quality-view"><div className={`gate ${activeQualityReport.passed ? "pass" : "block"}`}><span>{activeQualityReport.passed ? "✓" : "!"}</span><div><strong>{activeQualityReport.passed ? "交付检查通过" : "交付检查阻断"}</strong><p>检查 YAML 格式、真实来源证据、章节与事件覆盖；通过不代表 AI 文案无需作者复核。</p></div></div><div className="metric-grid">{Object.entries(activeQualityReport.metrics).map(([name, value]) => <Metric name={name} value={value} key={name} />)}</div><h3>交付问题</h3><IssueList issues={activeQualityReport.issues} /><h3>作者复核提示</h3><IssueList issues={result.issues} /></div>}
            {tab === "quality" && !activeQualityReport && <div className="quality-view"><div className="gate pending"><span>?</span><div><strong>质量门禁待校验</strong><p>当前 YAML 已修改，请重新校验后再判断是否可以交付。</p></div></div></div>}

            {tab === "yaml" && <div className="yaml-view"><div className="section-intro"><h2>可编辑 YAML</h2><p>修改后提交后端重新执行 Schema、证据链与覆盖质量门禁。<a href="https://github.com/YingJinyan/ai-novel-to-script/blob/main/docs/yaml-schema.md" target="_blank" rel="noreferrer">查看 YAML Schema 设计说明</a>；`project.generation` 仅用于项目级记录生成来源和模型，便于评委复现。</p></div><textarea aria-label="可编辑剧本 YAML" value={yamlDraft} onChange={(event) => { yamlRevision.current += 1; setYamlDraft(event.target.value); setYamlReport(null); setYamlDirty(true); setYamlMessage("当前修改尚未重新校验。"); }} /><div className="yaml-actions"><button className="primary" disabled={yamlValidating} onClick={() => void validateYamlDraft()}>{yamlValidating ? "校验中…" : "重新校验 YAML"}</button><button className="download secondary" disabled={!activeQualityReport?.passed} onClick={downloadYaml}>下载已通过版本</button><span className={yamlReport?.passed ? "yaml-pass" : "yaml-pending"}>{yamlMessage || "当前 YAML 来自生成结果，尚未手动修改。"}</span></div>{yamlReport && <IssueList issues={yamlReport.issues} />}</div>}
          </>}
        </section>
      </main>
    </div>
  );
}
