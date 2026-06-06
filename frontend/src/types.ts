export type Severity = "error" | "warning" | "info";

export interface Issue {
  code: string;
  severity: Severity;
  message: string;
  related_ids: string[];
}

export interface ParsedChapter {
  id: string;
  order: number;
  title: string;
  text: string;
}

export interface ParseResponse {
  eligible: boolean;
  chapters: ParsedChapter[];
  preamble: string;
  total_characters: number;
  issues: Issue[];
}

export interface SourceChapter {
  id: string;
  order: number;
  title: string;
  summary: string;
  content_sha256: string;
}

export interface NarrativeEvent {
  id: string;
  chapter_id: string;
  summary: string;
  importance: string;
  evidence: { quote: string; start_char: number; end_char: number };
}

export interface Scene {
  id: string;
  order: number;
  heading: { int_ext: string; location_id: string; time_of_day: string };
  purpose: string;
  character_ids: string[];
  beats: Array<{ type: string; text: string; character_id?: string; parenthetical?: string }>;
  traceability: {
    origin: string;
    source_chapter_ids: string[];
    source_event_ids: string[];
    adaptation_actions: Array<{ type: string; description: string; rationale: string }>;
  };
}

export interface ScreenplayDocument {
  schema_version: string;
  project: { title: string; logline: string };
  source: { chapter_count: number; total_characters: number; chapters: SourceChapter[] };
  story_bible: {
    locations: Array<{ id: string; name: string }>;
    characters: Array<{ id: string; name: string }>;
  };
  narrative_events: NarrativeEvent[];
  screenplay: { synopsis: string; scenes: Scene[] };
  [key: string]: unknown;
}

export interface QualityReport {
  passed: boolean;
  metrics: Record<string, number>;
  issues: Issue[];
}

export interface GenerationResponse {
  screenplay: ScreenplayDocument;
  source_texts: Record<string, string>;
  issues: Issue[];
  quality_report: QualityReport;
}

export interface ProviderStatus {
  provider: string;
  configured: boolean;
  model: string;
  base_url: string;
  mode: string;
}
