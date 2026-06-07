import type { GenerationResponse } from "./types";

export function buildValidationBundle(result: GenerationResponse) {
  return {
    bundle_version: "1.0.0",
    screenplay: result.screenplay,
    source_texts: result.source_texts,
    quality_report: result.quality_report,
    author_review_issues: result.issues,
  };
}
