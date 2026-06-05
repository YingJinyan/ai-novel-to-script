"""Validate the example screenplay structure and cross-object references."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "screenplay.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "screenplay.example.yaml"


def find_duplicates(values: list) -> set:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_references(screenplay: dict) -> list[str]:
    """Validate rules that JSON Schema cannot express clearly."""
    issues: list[str] = []
    chapters = screenplay["source"]["chapters"]
    events = screenplay["narrative_events"]
    characters = screenplay["story_bible"]["characters"]
    locations = screenplay["story_bible"]["locations"]
    scenes = screenplay["screenplay"]["scenes"]

    chapter_ids = {chapter["id"] for chapter in chapters}
    event_ids = {event["id"] for event in events}
    character_ids = {character["id"] for character in characters}
    location_ids = {location["id"] for location in locations}
    id_groups: dict[str, list[str]] = {
        "chapter": [item["id"] for item in chapters],
        "event": [item["id"] for item in events],
        "character": [item["id"] for item in characters],
        "location": [item["id"] for item in locations],
        "scene": [item["id"] for item in scenes],
    }
    for group, values in id_groups.items():
        for duplicate in sorted(find_duplicates(values)):
            issues.append(f"duplicate {group} id: {duplicate}")

    all_ids = [item_id for values in id_groups.values() for item_id in values]
    for duplicate in sorted(find_duplicates(all_ids)):
        issues.append(f"id is reused across entity types: {duplicate}")

    for label, values in {
        "chapter": [item["order"] for item in chapters],
        "scene": [item["order"] for item in scenes],
    }.items():
        for duplicate in sorted(find_duplicates(values)):
            issues.append(f"duplicate {label} order: {duplicate}")

    if screenplay["source"]["chapter_count"] != len(chapters):
        issues.append("source.chapter_count does not match the chapters array")

    for event in events:
        if event["chapter_id"] not in chapter_ids:
            issues.append(f"{event['id']} references unknown chapter {event['chapter_id']}")

    must_keep_ids = set(screenplay["adaptation_control"]["must_keep_event_ids"])
    unknown_must_keep = must_keep_ids - event_ids
    for event_id in sorted(unknown_must_keep):
        issues.append(f"adaptation_control references unknown must-keep event {event_id}")

    covered_event_ids: set[str] = set()
    for scene in scenes:
        heading = scene["heading"]
        traceability = scene["traceability"]
        scene_character_ids = set(scene["character_ids"])

        if heading["location_id"] not in location_ids:
            issues.append(f"{scene['id']} references unknown location {heading['location_id']}")

        for character_id in sorted(scene_character_ids - character_ids):
            issues.append(f"{scene['id']} references unknown character {character_id}")

        for beat in scene["beats"]:
            if beat["type"] == "dialogue":
                character_id = beat["character_id"]
                if character_id not in character_ids:
                    issues.append(f"{scene['id']} dialogue references unknown character {character_id}")
                elif character_id not in scene_character_ids:
                    issues.append(f"{scene['id']} dialogue character {character_id} is not in character_ids")

        source_chapter_ids = set(traceability["source_chapter_ids"])
        source_event_ids = set(traceability["source_event_ids"])
        for chapter_id in sorted(source_chapter_ids - chapter_ids):
            issues.append(f"{scene['id']} traces to unknown chapter {chapter_id}")
        for event_id in sorted(source_event_ids - event_ids):
            issues.append(f"{scene['id']} traces to unknown event {event_id}")
        event_chapter_ids = {
            event["chapter_id"] for event in events if event["id"] in source_event_ids
        }
        for chapter_id in sorted(event_chapter_ids - source_chapter_ids):
            issues.append(
                f"{scene['id']} source chapters omit the chapter for a traced event: {chapter_id}"
            )
        for chapter_id in sorted(source_chapter_ids - event_chapter_ids):
            issues.append(
                f"{scene['id']} lists a source chapter without a traced event: {chapter_id}"
            )
        covered_event_ids.update(source_event_ids)

        if traceability["origin"] == "invented" and not screenplay["adaptation_control"]["allow_new_events"]:
            issues.append(f"{scene['id']} is invented but adaptation_control.allow_new_events is false")
        action_types = {action["type"] for action in traceability["adaptation_actions"]}
        if traceability["origin"] == "invented" and "invent_event" not in action_types:
            issues.append(f"{scene['id']} is invented but has no invent_event adaptation action")
        source_only_actions = {"retain", "condense", "merge", "reorder", "rewrite"}
        if traceability["origin"] == "invented" and action_types & source_only_actions:
            issues.append(
                f"{scene['id']} is invented but declares source adaptation actions"
            )
        if (
            "invent_event" in action_types
            and not screenplay["adaptation_control"]["allow_new_events"]
        ):
            issues.append(
                f"{scene['id']} invents a story event but adaptation_control.allow_new_events is false"
            )

    for event_id in sorted(must_keep_ids - covered_event_ids):
        issues.append(f"must-keep event is not covered by any scene: {event_id}")

    return issues


def validate_source_evidence(screenplay: dict, source_texts: dict[str, str]) -> list[str]:
    """Verify evidence excerpts and hashes against the imported chapter text."""
    issues: list[str] = []
    available_texts: list[str] = []
    for chapter in screenplay["source"]["chapters"]:
        chapter_id = chapter["id"]
        source_text = source_texts.get(chapter_id)
        if source_text is None:
            issues.append(f"source text is unavailable for chapter {chapter_id}")
            continue
        available_texts.append(source_text)
        actual_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        if actual_hash != chapter["content_sha256"]:
            issues.append(f"content hash does not match source text for chapter {chapter_id}")

    for event in screenplay["narrative_events"]:
        chapter_id = event["chapter_id"]
        source_text = source_texts.get(chapter_id)
        if source_text is None:
            continue
        evidence = event["evidence"]
        start = evidence["start_char"]
        end = evidence["end_char"]
        if end <= start:
            issues.append(f"{event['id']} evidence range must end after it starts")
        elif source_text[start:end] != evidence["quote"]:
            issues.append(f"{event['id']} evidence quote does not match the source text range")

    if len(available_texts) == len(screenplay["source"]["chapters"]):
        actual_total = sum(len(text) for text in available_texts)
        if actual_total != screenplay["source"]["total_characters"]:
            issues.append("source.total_characters does not match the imported chapter texts")

    return issues


def build_quality_report(
    screenplay: dict,
    schema_errors: list[str] | None = None,
    reference_errors: list[str] | None = None,
    evidence_errors: list[str] | None = None,
) -> dict:
    """Compute review metrics from the current screenplay instead of storing stale values."""
    schema_errors = schema_errors or []
    reference_errors = reference_errors or []
    evidence_errors = evidence_errors or []
    chapters = screenplay["source"]["chapters"]
    events = screenplay["narrative_events"]
    scenes = screenplay["screenplay"]["scenes"]
    covered_event_ids = {
        event_id
        for scene in scenes
        for event_id in scene["traceability"]["source_event_ids"]
    }
    covered_chapter_ids = {
        chapter_id
        for scene in scenes
        for chapter_id in scene["traceability"]["source_chapter_ids"]
    }
    critical_event_ids = {event["id"] for event in events if event["importance"] == "critical"}
    must_keep_ids = set(screenplay["adaptation_control"]["must_keep_event_ids"])
    invented_scenes = [
        scene for scene in scenes if scene["traceability"]["origin"] == "invented"
    ]

    def ratio(covered: set, total: set) -> float:
        return round(len(covered & total) / len(total), 3) if total else 1.0

    all_event_ids = {event["id"] for event in events}
    all_chapter_ids = {chapter["id"] for chapter in chapters}
    issues = [
        {
            "code": "schema_validation_error",
            "severity": "error",
            "message": message,
            "related_ids": [],
        }
        for message in schema_errors
    ]
    issues.extend(
        {
            "code": "reference_validation_error",
            "severity": "error",
            "message": message,
            "related_ids": [],
        }
        for message in reference_errors
    )
    issues.extend(
        {
            "code": "evidence_validation_error",
            "severity": "error",
            "message": message,
            "related_ids": [],
        }
        for message in evidence_errors
    )
    for event_id in sorted(critical_event_ids - covered_event_ids):
        issues.append(
            {
                "code": "critical_event_missing",
                "severity": "error",
                "message": f"Critical event is not covered by any scene: {event_id}",
                "related_ids": [event_id],
            }
        )
    for event_id in sorted(must_keep_ids - covered_event_ids):
        issues.append(
            {
                "code": "must_keep_event_missing",
                "severity": "error",
                "message": f"Must-keep event is not covered by any scene: {event_id}",
                "related_ids": [event_id],
            }
        )
    target_scene_count = screenplay["adaptation_control"]["target_scene_count"]
    if len(scenes) != target_scene_count:
        issues.append(
            {
                "code": "target_scene_count_mismatch",
                "severity": "info",
                "message": (
                    f"Expected {target_scene_count} scenes but found {len(scenes)}."
                ),
                "related_ids": [],
            }
        )

    scene_count = len(scenes)
    traced_scene_count = sum(
        scene["traceability"]["origin"] == "source_adaptation"
        and bool(scene["traceability"]["source_event_ids"])
        for scene in scenes
    )
    return {
        "passed": not any(issue["severity"] == "error" for issue in issues),
        "metrics": {
            "chapter_coverage": ratio(covered_chapter_ids, all_chapter_ids),
            "event_coverage": ratio(covered_event_ids, all_event_ids),
            "critical_event_coverage": ratio(covered_event_ids, critical_event_ids),
            "must_keep_coverage": ratio(covered_event_ids, must_keep_ids),
            "source_traceability_coverage": (
                round(traced_scene_count / scene_count, 3) if scene_count else 0.0
            ),
            "invented_scene_ratio": (
                round(len(invented_scenes) / scene_count, 3) if scene_count else 0.0
            ),
            "target_scene_delta": len(scenes) - target_scene_count,
        },
        "issues": issues,
    }


def validate_screenplay(screenplay: object, source_texts: dict[str, str]) -> dict:
    """Return one safe structured report for valid or partially edited YAML."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    raw_schema_errors = sorted(
        validator.iter_errors(screenplay), key=lambda error: list(error.path)
    )
    schema_errors = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in raw_schema_errors
    ]
    if schema_errors:
        return {
            "passed": False,
            "metrics": {},
            "issues": [
                {
                    "code": "schema_validation_error",
                    "severity": "error",
                    "message": message,
                    "related_ids": [],
                }
                for message in schema_errors
            ],
        }

    reference_errors = validate_references(screenplay)
    evidence_errors = validate_source_evidence(screenplay, source_texts)
    return build_quality_report(
        screenplay,
        reference_errors=reference_errors,
        evidence_errors=evidence_errors,
    )


def load_example_source_texts() -> dict[str, str]:
    source_dir = ROOT / "examples" / "source"
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(source_dir.glob("chapter_*.txt"))
    }


def main() -> None:
    screenplay = yaml.safe_load(EXAMPLE_PATH.read_text(encoding="utf-8"))
    report = validate_screenplay(screenplay, load_example_source_texts())

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)
    print(f"Valid structure and references: {EXAMPLE_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
