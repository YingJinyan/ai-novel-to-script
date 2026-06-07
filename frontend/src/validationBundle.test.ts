import { describe, expect, it } from "vitest";
import type { GenerationResponse } from "./types";
import { buildValidationBundle } from "./validationBundle";

describe("validation bundle", () => {
  it("exports evidence and the current delivery status", () => {
    const result = {
      screenplay: { schema_version: "1.0.0" },
      source_texts: { chapter_001: "来源正文" },
      quality_report: {
        passed: true,
        metrics: { event_coverage: 1 },
        issues: [],
      },
      issues: [{
        code: "ai_semantic_review_required",
        severity: "warning",
        message: "请作者复核。",
        related_ids: [],
      }],
    } as unknown as GenerationResponse;

    expect(buildValidationBundle(result)).toEqual({
      bundle_version: "1.0.0",
      screenplay: result.screenplay,
      source_texts: result.source_texts,
      quality_report: result.quality_report,
      author_review_issues: result.issues,
    });
  });
});
