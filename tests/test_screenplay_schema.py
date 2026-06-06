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
    validate_generation_contract,
    validate_references,
    validate_scene_grounding,
    validate_screenplay,
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
    assert validate_generation_contract(screenplay) == []
    assert validate_scene_grounding(screenplay) == []


def test_schema_allows_empty_character_list_when_no_person_is_reliably_identified(
    screenplay: dict,
) -> None:
    screenplay["story_bible"]["characters"] = []
    for scene in screenplay["screenplay"]["scenes"]:
        scene["character_ids"] = []
        scene["beats"] = [beat for beat in scene["beats"] if beat["type"] != "dialogue"]

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


def test_rejects_incorrect_total_character_count(screenplay: dict) -> None:
    screenplay["source"]["total_characters"] += 1

    errors = validate_source_evidence(screenplay, load_example_source_texts())

    assert "source.total_characters does not match the imported chapter texts" in errors


def test_rejects_qiniu_mode_with_a_forged_provider_or_empty_model(screenplay: dict) -> None:
    screenplay["project"]["generation"] = {
        "provider": "local-rules",
        "model": "",
        "mode": "qiniu_ai",
        "fallback_reason": "",
    }

    errors = validate_generation_contract(screenplay)

    assert "qiniu_ai generation mode requires provider qiniu-ai" in errors
    assert "qiniu_ai generation mode requires a non-empty model" in errors


def test_rejects_qiniu_provider_outside_qiniu_mode(screenplay: dict) -> None:
    screenplay["project"]["generation"]["provider"] = "qiniu-ai"

    assert (
        "provider qiniu-ai requires qiniu_ai generation mode"
        in validate_generation_contract(screenplay)
    )


def test_rejects_compatible_ai_without_a_model_or_with_a_reserved_provider(
    screenplay: dict,
) -> None:
    screenplay["project"]["generation"] = {
        "provider": "local-rules",
        "model": "",
        "mode": "compatible_ai",
        "fallback_reason": "",
    }

    errors = validate_generation_contract(screenplay)

    assert (
        "compatible_ai generation mode cannot use a reserved Qiniu or local provider"
        in errors
    )
    assert "compatible_ai generation mode requires a non-empty model" in errors


def test_rejects_curated_demo_with_a_forged_provider_or_model(screenplay: dict) -> None:
    screenplay["project"]["generation"] = {
        "provider": "curated-demo",
        "model": "forged-model",
        "mode": "curated_demo",
        "fallback_reason": "",
    }

    errors = validate_generation_contract(screenplay)

    assert (
        "curated_demo generation mode requires provider local-curated-example"
        in errors
    )
    assert "curated_demo generation mode requires an empty model" in errors


def test_rejects_any_source_scene_that_drops_source_evidence(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][0]["beats"] = [
        {"type": "action", "text": "不包含来源证据的动作。"}
    ]
    screenplay["project"]["generation"] = {
        "provider": "qiniu-ai",
        "model": "deepseek-v3",
        "mode": "qiniu_ai",
        "fallback_reason": "",
    }

    errors = validate_scene_grounding(screenplay)

    assert (
        "scene_1 action text does not retain evidence quote for event_letter_found"
        in errors
    )


def test_rejects_curated_demo_relabel_that_drops_source_evidence(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][0]["beats"] = [
        {"type": "action", "text": "不包含来源证据的动作。"}
    ]

    assert validate_scene_grounding(screenplay)


def test_safe_validation_rechecks_qiniu_grounding_after_yaml_edit(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"][0]["beats"] = [
        {"type": "action", "text": "不包含来源证据的动作。"}
    ]
    screenplay["project"]["generation"] = {
        "provider": "qiniu-ai",
        "model": "deepseek-v3",
        "mode": "qiniu_ai",
        "fallback_reason": "",
    }

    report = validate_screenplay(screenplay, load_example_source_texts())

    assert report["passed"] is False
    assert "evidence_validation_error" in {issue["code"] for issue in report["issues"]}


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

    assert report["passed"] is False
    assert report["metrics"]["critical_event_coverage"] == 0.5
    assert report["metrics"]["target_scene_delta"] == -2
    assert {issue["code"] for issue in report["issues"]} == {
        "critical_event_missing",
        "must_keep_event_missing",
        "target_scene_count_mismatch",
    }


def test_quality_report_includes_validation_errors_and_fails(screenplay: dict) -> None:
    report = build_quality_report(
        screenplay,
        schema_errors=["screenplay.scenes: [] should be non-empty"],
        reference_errors=["scene_1 references unknown location"],
        evidence_errors=["event_letter_found evidence quote does not match"],
    )

    assert report["passed"] is False
    assert {issue["code"] for issue in report["issues"]} >= {
        "schema_validation_error",
        "reference_validation_error",
        "evidence_validation_error",
    }


def test_quality_report_handles_empty_scenes(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"] = []

    report = build_quality_report(
        screenplay,
        schema_errors=["screenplay.scenes: [] should be non-empty"],
    )

    assert report["passed"] is False
    assert report["metrics"]["source_traceability_coverage"] == 0.0
    assert report["metrics"]["invented_scene_ratio"] == 0.0


def test_invented_scene_cannot_declare_source_adaptation_actions(screenplay: dict) -> None:
    screenplay["adaptation_control"]["allow_new_events"] = True
    screenplay["screenplay"]["scenes"][0]["traceability"] = {
        "origin": "invented",
        "source_chapter_ids": [],
        "source_event_ids": [],
        "adaptation_actions": [
            {
                "type": "invent_event",
                "description": "新增剧情事件。",
                "rationale": "测试新增场次。",
            },
            {
                "type": "retain",
                "description": "不合理的来源改编动作。",
                "rationale": "测试语义冲突。",
            },
        ],
    }

    errors = validate_references(screenplay)

    assert "scene_1 is invented but declares source adaptation actions" in errors


def test_safe_validation_reports_deleted_required_field(screenplay: dict) -> None:
    del screenplay["screenplay"]["scenes"][0]["traceability"]

    report = validate_screenplay(screenplay, load_example_source_texts())

    assert report["passed"] is False
    assert report["metrics"] == {}
    assert report["issues"][0]["code"] == "schema_validation_error"
    assert "traceability" in report["issues"][0]["message"]


def test_safe_validation_reports_wrong_field_type(screenplay: dict) -> None:
    screenplay["screenplay"]["scenes"] = "not-an-array"

    report = validate_screenplay(screenplay, load_example_source_texts())

    assert report["passed"] is False
    assert report["metrics"] == {}
    assert report["issues"][0]["code"] == "schema_validation_error"


def test_safe_validation_reports_deleted_top_level_section(screenplay: dict) -> None:
    del screenplay["adaptation_control"]

    report = validate_screenplay(screenplay, load_example_source_texts())

    assert report["passed"] is False
    assert report["metrics"] == {}
    assert report["issues"][0]["code"] == "schema_validation_error"
