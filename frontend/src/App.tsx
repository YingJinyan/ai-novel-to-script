import { useEffect, useMemo, useRef, useState } from "react";
import yaml from "js-yaml";
import { ApiError, generateAI, generateLocal, getQiniuModels, getQiniuStatus, parseNovel, validateScreenplay } from "./api";
import type { GenerationResponse, Issue, ParseResponse, QualityReport, Scene } from "./types";

type ResultTab = "script" | "coverage" | "quality" | "yaml";
type GenerationMode = "local" | "qiniu";
type ModelGroup = "recommended" | "general" | "thinking" | "vision";

const issueLabel = { error: "阻断", warning: "注意", info: "信息" };
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
const RECOMMENDED_QINIU_MODELS = [
  "deepseek-v3",
  "deepseek-v3.1",
  "deepseek/deepseek-v3.1-terminus",
  "qwen3-max",
  "moonshotai/kimi-k2.5",
];

function modelGroup(model: string): ModelGroup {
  const normalized = model.toLowerCase();
  if (RECOMMENDED_QINIU_MODELS.includes(model)) return "recommended";
  if (normalized.includes("vl") || normalized.includes("vision")) return "vision";
  if (normalized.includes("thinking") || normalized.includes("reason") || normalized.includes("r1")) {
    return "thinking";
  }
  return "general";
}

function modelGuidance(model: string): string {
  switch (modelGroup(model)) {
    case "recommended": return "推荐：适合结构化文本改编与稳定演示。";
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
    { recommended: [], general: [], thinking: [], vision: [] },
  );
}

function Metric({ name, value }: { name: string; value: number }) {
  const isRatio = RATIO_METRICS.has(name);
  const percentage = Math.round(value * 100);
  const label = isRatio ? `${percentage}%` : String(value);
  return (
    <div className="metric">
      <div className="metric-row"><span>{name.replaceAll("_", " ")}</span><strong>{label}</strong></div>
      {isRatio && <div className="meter"><i style={{ width: `${Math.max(0, Math.min(100, percentage))}%` }} /></div>}
    </div>
  );
}

function SceneDetail({ scene, result }: { scene: Scene; result: GenerationResponse }) {
  const locations = result.screenplay.story_bible?.locations ?? [];
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
            <span>{beat.type}</span>
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
  const [error, setError] = useState("");
  const [blockedQuality, setBlockedQuality] = useState<QualityReport | null>(null);
  const [generationMode, setGenerationMode] = useState<GenerationMode>("local");
  const [qiniuModels, setQiniuModels] = useState<string[]>([]);
  const [selectedQiniuModel, setSelectedQiniuModel] = useState("");
  const [providerMessage, setProviderMessage] = useState("");
  const [providerLoading, setProviderLoading] = useState(false);
  const [yamlDraft, setYamlDraft] = useState("");
  const [yamlReport, setYamlReport] = useState<QualityReport | null>(null);
  const [yamlMessage, setYamlMessage] = useState("");
  const [yamlValidating, setYamlValidating] = useState(false);
  const [yamlDirty, setYamlDirty] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const sourceRevision = useRef(0);

  const scenes = result?.screenplay.screenplay.scenes ?? [];
  const yamlText = useMemo(() => result ? yaml.dump(result.screenplay, { noRefs: true, lineWidth: 100 }) : "", [result]);
  const activeQualityReport = yamlDirty ? null : yamlReport ?? result?.quality_report ?? null;

  useEffect(() => {
    setYamlDraft(yamlText);
    setYamlReport(null);
    setYamlMessage("");
    setYamlDirty(false);
  }, [yamlText]);

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
      const preferred = response.models.includes(response.selected_model)
        ? response.selected_model
        : RECOMMENDED_QINIU_MODELS.find((model) => response.models.includes(model))
          ?? response.models[0]
          ?? "";
      setSelectedQiniuModel(preferred);
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
    setLoading("parse"); setError(""); setBlockedQuality(null); setResult(null);
    try {
      setParsed(await parseNovel(novelText));
    } catch (err) {
      setParsed(null); setError(err instanceof Error ? err.message : "解析请求失败。");
    } finally { setLoading(null); }
  }

  async function handleGenerate() {
    if (!title.trim()) return setError("请填写项目名称。");
    if (!parsed?.eligible) return setError("当前解析结果未达到生成条件，请先处理阻断问题。");
    if (generationMode === "qiniu" && !selectedQiniuModel) {
      return setError("七牛 AI 尚无可用模型，请刷新模型列表或使用离线规则模式。");
    }
    setLoading("generate"); setError(""); setBlockedQuality(null); setResult(null);
    const requestedRevision = sourceRevision.current;
    try {
      const generated = generationMode === "qiniu"
        ? await generateAI(novelText, title.trim(), selectedQiniuModel)
        : await generateLocal(novelText, title.trim());
      if (requestedRevision === sourceRevision.current) {
        setResult(generated); setSelectedScene(0); setTab("script");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成请求失败。");
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
    setNovelText(importedText); setParsed(null); setResult(null); setBlockedQuality(null); setError("");
  }

  function loadSample() {
    sourceRevision.current += 1;
    setNovelText(SAMPLE_NOVEL);
    setTitle("雨夜来信");
    setParsed(null);
    setResult(null);
    setBlockedQuality(null);
    setError("");
  }

  function selectGenerationMode(mode: GenerationMode) {
    setGenerationMode(mode);
    setResult(null);
    setBlockedQuality(null);
    setError("");
  }

  function downloadYaml() {
    const url = URL.createObjectURL(new Blob([yamlDraft || yamlText], { type: "text/yaml;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url; link.download = `${title.trim() || "screenplay"}.yaml`; link.click();
    URL.revokeObjectURL(url);
  }

  async function validateYamlDraft() {
    if (!result) return;
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
    const content = JSON.stringify(
      { screenplay: result.screenplay, source_texts: result.source_texts },
      null,
      2,
    );
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

  return (
    <div className="app-shell">
      <header>
        <div className="brand"><span className="brand-mark">溯</span><div><strong>溯源剧本工作台</strong><small>可信 · 可控 · 可追溯</small></div></div>
        <div className="mode"><i />{generationMode === "qiniu" ? `七牛 AI · ${selectedQiniuModel}` : "离线规则模式（不调用 AI）"}</div>
      </header>

      <main>
        <section className="intro">
          <div><p className="eyebrow">NOVEL → SCREENPLAY</p><h1>让每一个场次，都有出处。</h1><p>导入至少 3 章小说，先检查输入，再生成可验证、可下载的结构化剧本。</p></div>
          <div className="steps"><span className={parsed ? "done" : "active"}>01 输入检查</span><span className={result ? "done" : parsed?.eligible ? "active" : ""}>02 本地生成</span><span className={result ? "active" : ""}>03 溯源审阅</span></div>
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
              <div className="provider-picker"><button className={generationMode === "local" ? "selected" : ""} disabled={!!loading} onClick={() => selectGenerationMode("local")}><strong>离线规则</strong><span>不调用 AI，稳定生成可追溯骨架</span></button><button className={generationMode === "qiniu" ? "selected" : ""} disabled={!!loading || !selectedQiniuModel} onClick={() => selectGenerationMode("qiniu")}><strong>七牛 AI</strong><span>{selectedQiniuModel ? `${selectedQiniuModel} · 受限润色` : "未读取到可用模型"}</span></button></div>
              <div className="model-picker"><label>七牛模型<select disabled={!!loading || providerLoading || !qiniuModels.length} value={selectedQiniuModel} onChange={(event) => { setSelectedQiniuModel(event.target.value); if (generationMode === "qiniu") setResult(null); }}>{qiniuModels.length ? <><optgroup label="推荐用于小说改编">{qiniuModelGroups.recommended.map((model) => <option value={model} key={model}>{model}</option>)}</optgroup><optgroup label="通用文本模型">{qiniuModelGroups.general.map((model) => <option value={model} key={model}>{model}</option>)}</optgroup><optgroup label="推理模型（可能较慢）">{qiniuModelGroups.thinking.map((model) => <option value={model} key={model}>{model}</option>)}</optgroup><optgroup label="视觉模型（当前任务不推荐）">{qiniuModelGroups.vision.map((model) => <option value={model} key={model}>{model}</option>)}</optgroup></> : <option value="">暂无可用模型</option>}</select></label><button className="text-button" disabled={providerLoading || !!loading} onClick={() => void refreshQiniuProvider()}>{providerLoading ? "读取中…" : "刷新七牛模型"}</button><span>{providerMessage} {selectedQiniuModel && modelGuidance(selectedQiniuModel)}</span></div>
              <div className="generate-box"><label>项目名称<input disabled={!!loading} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：雨夜来信" /></label><button className="primary generate" disabled={!parsed.eligible || !!loading} onClick={handleGenerate}>{loading === "generate" ? "正在生成…" : generationMode === "qiniu" ? "使用七牛 AI 润色" : "生成结构化剧本"}</button></div>
            </>}
          </div>
        </section>

        {error && <div role="alert" className="error-banner"><strong>请求未完成</strong><span>{error}</span></div>}
        {blockedQuality && <section className="blocked-quality panel"><div className="gate block"><span>!</span><div><strong>质量门禁阻断</strong><p>后端拒绝返回未通过校验的生成结果，以下为真实诊断。</p></div></div><div className="metric-grid">{Object.entries(blockedQuality.metrics).map(([name, value]) => <Metric name={name} value={value} key={name} />)}</div><IssueList issues={blockedQuality.issues} /></section>}

        <section className="workspace panel">
          <div className="workspace-head"><div><span className="panel-number">03</span><div><h2>剧本审阅工作台</h2><p>{result ? result.screenplay.project.title : "生成后可审阅场次、证据与质量门禁"}</p></div></div>{result && <div className="download-actions"><button className="download secondary" onClick={downloadValidationBundle}>下载验证包</button><button className="download" onClick={downloadYaml}>下载剧本 YAML</button></div>}</div>
          {!result ? <div className="workspace-empty"><span>SCREENPLAY / TRACE / QUALITY</span><h2>尚未生成剧本</h2><p>完成输入检查并生成后，工作台将展示真实接口返回的数据。</p></div> : <>
            <nav className="tabs" aria-label="结果视图">
              <button className={tab === "script" ? "active" : ""} onClick={() => setTab("script")}>场次与证据 <b>{scenes.length}</b></button>
              <button className={tab === "coverage" ? "active" : ""} onClick={() => setTab("coverage")}>章节覆盖矩阵</button>
              <button className={tab === "quality" ? "active" : ""} onClick={() => setTab("quality")}>质量门禁 <b className={activeQualityReport ? activeQualityReport.passed ? "good" : "bad" : "pending"}>{activeQualityReport ? activeQualityReport.passed ? "通过" : "阻断" : "待校验"}</b></button>
              <button className={tab === "yaml" ? "active" : ""} onClick={() => setTab("yaml")}>原始 YAML</button>
            </nav>

            {tab === "script" && <div className="script-layout">
              <aside><div className="synopsis"><span>剧本概要</span><p>{result.screenplay.screenplay.synopsis}</p></div>{scenes.map((scene, index) => <button key={scene.id} className={selectedScene === index ? "active" : ""} onClick={() => setSelectedScene(index)}><span>{String(scene.order).padStart(2, "0")}</span><div><strong>{scene.heading.int_ext} · {scene.heading.time_of_day}</strong><small>{scene.purpose}</small></div></button>)}</aside>
              {scenes[selectedScene] && <SceneDetail scene={scenes[selectedScene]} result={result} />}
            </div>}

            {tab === "coverage" && <div className="coverage-view"><div className="section-intro"><h2>事件覆盖矩阵</h2><p>逐个事件检查是否被场次采用，避免同章内遗漏被隐藏。</p></div><div className="coverage-table"><div className="coverage-row head"><span>来源章节</span><span>叙事事件</span><span>关联场次</span><span>状态</span></div>{eventCoverage.map(({ chapter, event, linkedScenes }) => <div className="coverage-row" key={event.id}><span><strong>{chapter?.title ?? event.chapter_id}</strong><small>{event.chapter_id}</small></span><span><strong>{event.id}</strong><small>{event.summary}</small></span><span>{linkedScenes.map((s) => s.id).join(", ") || "—"}</span><span className={linkedScenes.length ? "covered" : "uncovered"}>{linkedScenes.length ? "已覆盖" : "未覆盖"}</span></div>)}</div></div>}

            {tab === "quality" && activeQualityReport && <div className="quality-view"><div className={`gate ${activeQualityReport.passed ? "pass" : "block"}`}><span>{activeQualityReport.passed ? "✓" : "!"}</span><div><strong>{activeQualityReport.passed ? "质量门禁通过" : "质量门禁阻断"}</strong><p>指标与问题来自后端校验报告。</p></div></div><div className="metric-grid">{Object.entries(activeQualityReport.metrics).map(([name, value]) => <Metric name={name} value={value} key={name} />)}</div><h3>质量问题</h3><IssueList issues={activeQualityReport.issues} /><h3>生成过程问题</h3><IssueList issues={result.issues} /></div>}
            {tab === "quality" && !activeQualityReport && <div className="quality-view"><div className="gate pending"><span>?</span><div><strong>质量门禁待校验</strong><p>当前 YAML 已修改，请重新校验后再判断是否可以交付。</p></div></div></div>}

            {tab === "yaml" && <div className="yaml-view"><div className="section-intro"><h2>可编辑 YAML</h2><p>修改后提交后端重新执行 Schema、证据链与覆盖质量门禁。</p></div><textarea aria-label="可编辑剧本 YAML" value={yamlDraft} onChange={(event) => { setYamlDraft(event.target.value); setYamlReport(null); setYamlDirty(true); setYamlMessage("当前修改尚未重新校验。"); }} /><div className="yaml-actions"><button className="primary" disabled={yamlValidating} onClick={() => void validateYamlDraft()}>{yamlValidating ? "校验中…" : "重新校验 YAML"}</button><button className="download secondary" onClick={downloadYaml}>下载当前草稿</button><span className={yamlReport?.passed ? "yaml-pass" : "yaml-pending"}>{yamlMessage || "当前 YAML 来自生成结果，尚未手动修改。"}</span></div>{yamlReport && <IssueList issues={yamlReport.issues} />}</div>}
          </>}
        </section>
      </main>
    </div>
  );
}
