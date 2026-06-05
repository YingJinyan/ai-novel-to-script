from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from scripts.validate_example import (
    build_quality_report,
    load_example_source_texts,
    validate_references,
    validate_source_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "screenplay.schema.json").read_text(encoding="utf-8"))
EXAMPLE = yaml.safe_load((ROOT / "examples" / "screenplay.example.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def screenplay() -> dict:
    return copy.deepcopy(EXAMPLE)


def schema_errors(screenplay: dict) -> list:
    return list(Draft202012Validator(SCHEMA).iter_errors(screenplay))


def test_schema_itself_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_example_passes_structure_and_business_rules(screenplay: dict) -> None:
    assert schema_errors(screenplay) == []
    assert validate_references(screenplay) == []
    assert validate_source_evidence(screenplay, load_example_source_texts()) == []


def test_rejects_source_with_fewer_than_three_chapters(screenplay: dict) -> None:
    screenplay["source"]["chapters"] = screenplay["source"]["chapters"][:2]
    screenplay["source"]["chapter_count"] = 2

    errors = schema_errors(screenplay)

    assert errors
    assert any(list(error.absolute_path) == ["source", "chapter_count"] for error in errors)


def test_rejects_unknown_dialogue_character(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][1]["beats"][1]["character_id"] = "character_unknown"

    errors = validate_references(screenplay)

    assert "scene_2 dialogue references unknown character character_unknown" in errors


def test_rejects_uncovered_must_keep_event(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][0]["traceability"]["source_event_ids"] = [
        "event_ticket_handover"
    ]

    errors = validate_references(screenplay)

    assert "must-keep event is not covered by any scene: event_letter_found" in errors


def test_rejects_invented_scene_when_author_forbids_new_events(screenplay: dict) -> None:
    scene = screenplay["screenplay"]["scenes"][0]
    scene["traceability"] = {
        "origin": "invented",
        "source_chapter_ids": [],
        "source_event_ids": [],
        "adaptation_actions": [
            {
                "type": "invent_event",
                "description": "新增梦境。",
                "rationale": "测试未经允许的新增内容。",
            }
        ],
    }

    errors = validate_references(screenplay)

    assert "scene_1 is invented but adaptation_control.allow_new_events is false" in errors


def test_rejects_source_chapter_without_a_traced_event(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][0]["traceability"]["source_chapter_ids"].append("chapter_2")

    errors = validate_references(screenplay)

    assert "scene_1 lists a source chapter without a traced event: chapter_2" in errors


def test_rejects_event_when_its_chapter_is_missing_from_scene_sources(screenplay: dict) -> None:
    traceability = screenplay["screenplay"]["scenes"][0]["traceability"]
    traceability["source_event_ids"] = ["event_station_meeting"]

    errors = validate_references(screenplay)

    assert "scene_1 source chapters omit the chapter for a traced event: chapter_2" in errors


def test_rejects_forged_evidence_quote(screenplay: dict) -> None:
    screenplay["narrative_events"][0]["evidence"]["quote"] = "这句话不在原文中。"

    errors = validate_source_evidence(screenplay, load_example_source_texts())

    assert "event_letter_found evidence quote does not match the source text range" in errors


def test_rejects_source_text_when_content_hash_changes(screenplay: dict) -> None:
    source_texts = load_example_source_texts()
    source_texts["chapter_1"] += "被篡改"

    errors = validate_source_evidence(screenplay, source_texts)

    assert "content hash does not match source text for chapter chapter_1" in errors


def test_rejects_invent_event_action_when_author_forbids_it(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][0]["traceability"]["adaptation_actions"].append(
        {
            "type": "invent_event",
            "description": "新增剧情事件。",
            "rationale": "测试禁止新增事件能否被绕过。",
        }
    )

    errors = validate_references(screenplay)

    assert "scene_1 invents a story event but adaptation_control.allow_new_events is false" in errors


def test_allows_invented_detail_when_new_story_events_are_forbidden(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][0]["traceability"]["adaptation_actions"].append(
        {
            "type": "invent_detail",
            "description": "补充雨声作为可视化细节。",
            "rationale": "不改变原剧情事件。",
        }
    )

    assert validate_references(screenplay) == []


def test_rejects_duplicate_id_across_entity_types(screenplay: dict) -> None:
    screenplay["story_bible"]["locations"][0]["id"] = "character_lin_xia"

    errors = validate_references(screenplay)

    assert "id is reused across entity types: character_lin_xia" in errors


def test_rejects_duplicate_scene_order(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][1]["order"] = 1

    errors = validate_references(screenplay)

    assert "duplicate scene order: 1" in errors


def test_rejects_unknown_location(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][0]["heading"]["location_id"] = "location_unknown"

    errors = validate_references(screenplay)

    assert "scene_1 references unknown location location_unknown" in errors


def test_quality_report_flags_missing_critical_event_and_scene_count(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"] = screenplay["screenplay"]["scenes"][:1]

    report = build_quality_report(screenplay)

    assert report["metrics"]["critical_event_coverage"] == 0.5
    assert report["metrics"]["target_scene_delta"] == -2
    assert {issue["code"] for issue in report["issues"]} == {
        "critical_event_missing",
        "target_scene_count_mismatch",
    }
