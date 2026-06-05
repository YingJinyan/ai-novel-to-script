"""Validate the example screenplay structure and cross-object references."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "screenplay.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "screenplay.example.yaml"


def find_duplicates(values: list[str]) -> set[str]:
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
    scene_ids = {scene["id"] for scene in scenes}

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
        for evidence in traceability["evidence"]:
            if evidence["chapter_id"] not in chapter_ids:
                issues.append(
                    f"{scene['id']} evidence references unknown chapter {evidence['chapter_id']}"
                )
            elif evidence["chapter_id"] not in source_chapter_ids:
                issues.append(
                    f"{scene['id']} evidence chapter is not listed in source_chapter_ids: "
                    f"{evidence['chapter_id']}"
                )
        covered_event_ids.update(source_event_ids)

        if traceability["origin"] == "invented" and not screenplay["adaptation_control"]["allow_new_events"]:
            issues.append(f"{scene['id']} is invented but adaptation_control.allow_new_events is false")
        action_types = {action["type"] for action in traceability["adaptation_actions"]}
        if traceability["origin"] == "invented" and "invent" not in action_types:
            issues.append(f"{scene['id']} is invented but has no invent adaptation action")

    for event_id in sorted(must_keep_ids - covered_event_ids):
        issues.append(f"must-keep event is not covered by any scene: {event_id}")

    return issues


def main() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    screenplay = yaml.safe_load(EXAMPLE_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(screenplay), key=lambda error: list(error.path))

    if schema_errors:
        for error in schema_errors:
            path = ".".join(str(part) for part in error.absolute_path) or "<root>"
            print(f"{path}: {error.message}")
        raise SystemExit(1)

    reference_errors = validate_references(screenplay)
    if reference_errors:
        for error in reference_errors:
            print(f"business rule: {error}")
        raise SystemExit(1)

    print(f"Valid structure and references: {EXAMPLE_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
