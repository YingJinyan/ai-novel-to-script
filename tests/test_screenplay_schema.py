from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from scripts.validate_example import validate_references


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
        "evidence": [],
        "adaptation_actions": [
            {
                "type": "invent",
                "description": "新增梦境。",
                "rationale": "测试未经允许的新增内容。",
            }
        ],
    }

    errors = validate_references(screenplay)

    assert "scene_1 is invented but adaptation_control.allow_new_events is false" in errors


def test_rejects_evidence_for_an_unlisted_source_chapter(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][0]["traceability"]["evidence"][0]["chapter_id"] = "chapter_2"

    errors = validate_references(screenplay)

    assert "scene_1 evidence chapter is not listed in source_chapter_ids: chapter_2" in errors


def test_rejects_event_when_its_chapter_is_missing_from_scene_sources(screenplay: dict) -> None:
    traceability = screenplay["screenplay"]["scenes"][0]["traceability"]
    traceability["source_event_ids"] = ["event_station_meeting"]

    errors = validate_references(screenplay)

    assert "scene_1 source chapters omit the chapter for a traced event: chapter_2" in errors
