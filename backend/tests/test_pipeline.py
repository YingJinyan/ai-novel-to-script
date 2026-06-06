from __future__ import annotations

import hashlib

import pytest

from backend.pipeline import (
    LocalPipelineError,
    analyze_chapters,
    generate_local_screenplay,
    parse_chapters,
)
from scripts.validate_example import validate_screenplay


NOVEL = """序言不会被当作章节正文。

第1章 雨夜来信
雨夜里，林夏来到废弃车站。林夏说：“我一定会找到真相。”

第一章后的附加文本不会出现。
第二章 旧站守候
陈默站在废弃车站门口。陈默问：“你终于来了？”

Chapter 3 The Ticket
林夏走进办公室，发现桌上留下了一张旧车票。
"""


def test_parse_chinese_and_english_chapter_headings() -> None:
    chapters = parse_chapters(NOVEL)

    assert [chapter.id for chapter in chapters] == [
        "chapter_001",
        "chapter_002",
        "chapter_003",
    ]
    assert [chapter.title for chapter in chapters] == [
        "第1章 雨夜来信",
        "第二章 旧站守候",
        "Chapter 3 The Ticket",
    ]
    assert all(chapter.text for chapter in chapters)


def test_rejects_novel_with_fewer_than_three_chapters() -> None:
    with pytest.raises(LocalPipelineError, match="至少需要 3 个章节，当前仅识别到 2 个"):
        parse_chapters("第1章 开始\n正文。\n第二章 继续\n正文。")

    result = analyze_chapters("第1章 开始\n正文。\n第二章 继续\n正文。")
    assert result.eligible is False
    assert len(result.chapters) == 2
    assert result.total_characters == len("第1章 开始\n正文。\n第二章 继续\n正文。")
    assert result.issues[-1]["code"] == "chapter_count_too_low"


def test_rejects_empty_chapter_body() -> None:
    with pytest.raises(LocalPipelineError, match="没有正文"):
        parse_chapters("第1章 开始\n正文。\n第二章 空章\n第三章 结尾\n正文。")

    result = analyze_chapters("第1章 开始\n正文。\n第二章 空章\n第三章 结尾\n正文。")
    assert result.eligible is False
    assert len(result.chapters) == 3
    assert "empty_chapter" in {issue["code"] for issue in result.issues}


def test_generation_is_deterministic_and_hashes_exact_source_text() -> None:
    first = generate_local_screenplay(NOVEL)
    second = generate_local_screenplay(NOVEL)

    assert first == second
    for chapter in first.screenplay["source"]["chapters"]:
        source_text = first.source_texts[chapter["id"]]
        assert chapter["content_sha256"] == hashlib.sha256(
            source_text.encode("utf-8")
        ).hexdigest()


def test_events_use_real_evidence_ranges() -> None:
    result = generate_local_screenplay(NOVEL)

    for event in result.screenplay["narrative_events"]:
        evidence = event["evidence"]
        source_text = result.source_texts[event["chapter_id"]]
        assert source_text[evidence["start_char"] : evidence["end_char"]] == evidence["quote"]


def test_local_rules_do_not_guess_characters_locations_or_dialogue() -> None:
    result = generate_local_screenplay(NOVEL)
    screenplay = result.screenplay

    location_names = {item["name"] for item in screenplay["story_bible"]["locations"]}
    beats = [beat for scene in screenplay["screenplay"]["scenes"] for beat in scene["beats"]]

    assert screenplay["story_bible"]["characters"] == []
    assert location_names == {"未指定场景"}
    assert all(beat["type"] == "action" for beat in beats)


def test_warns_instead_of_guessing_dialogue_speakers() -> None:
    result = generate_local_screenplay(
        "第一章 相遇\n林夏说：“你是谁？”\n陈默回答：“守站人。”\n"
        "第二章 追逐\n林夏冲进雨幕。\n"
        "第三章 结束\n天亮了。"
    )

    issue = next(
        issue for issue in result.issues
        if issue["code"] == "manual_character_review_required"
    )
    assert issue["message"] == "第一章 相遇 包含对白，生成后请复核说话人归属。"
    assert "本地规则模式" not in issue["message"]
    assert result.screenplay["story_bible"]["characters"] == []


def test_generates_at_least_one_traceable_scene_per_chapter() -> None:
    result = generate_local_screenplay(NOVEL)
    screenplay = result.screenplay
    scenes = screenplay["screenplay"]["scenes"]

    assert len(scenes) == screenplay["source"]["chapter_count"]
    for scene in scenes:
        assert scene["beats"]
        assert scene["traceability"]["origin"] == "source_adaptation"
        assert len(scene["traceability"]["source_chapter_ids"]) == 1
        assert len(scene["traceability"]["source_event_ids"]) == 1
        assert scene["traceability"]["adaptation_actions"][0]["type"] == "rewrite"


def test_complete_local_result_passes_existing_schema_and_business_validation() -> None:
    result = generate_local_screenplay(NOVEL, title="雨夜旧站")

    report = validate_screenplay(result.screenplay, result.source_texts)

    assert report["passed"] is True
    assert report["issues"] == []
    assert report["metrics"]["chapter_coverage"] == 1.0
    assert report["metrics"]["event_coverage"] == 1.0
    assert report["metrics"]["source_traceability_coverage"] == 1.0


def test_does_not_invent_character_and_uses_unspecified_location_per_chapter() -> None:
    result = generate_local_screenplay(
        "第1章 一\n风吹过。\n第二章 二\n雨停了。\nChapter 3 End\n天亮了。"
    )

    assert result.screenplay["story_bible"]["characters"] == []
    assert result.screenplay["story_bible"]["locations"][0]["name"] == "未指定场景"
    assert {
        scene["heading"]["location_id"] for scene in result.screenplay["screenplay"]["scenes"]
    } == {"location_001"}
    assert validate_screenplay(result.screenplay, result.source_texts)["passed"] is True


def test_supports_markdown_headings_spacing_bom_and_mixed_case() -> None:
    chapters = parse_chapters(
        "\ufeff# 第 01 章 开始\r\n正文一。\r\n"
        "## 第十二章 继续\r\n正文二。\r\n"
        "### CHAPTER 100: Ending\r\n正文三。"
    )

    assert len(chapters) == 3
    assert chapters[0].title == "第 01 章 开始"


def test_supports_large_chinese_chapter_numbers_without_matching_inline_text() -> None:
    result = analyze_chapters(
        "作品名称：测试\n"
        "他翻到第一章，却没有继续阅读。\n"
        "第一章 开始\n正文一。\n"
        "第十二章 继续\n正文二。\n"
        "第一百零一章 结束\n正文三。"
    )

    assert len(result.chapters) == 3
    assert result.chapters[-1].title == "第一百零一章 结束"
    assert result.preamble.startswith("作品名称")
    assert "preamble_ignored" in {issue["code"] for issue in result.issues}


def test_returns_warnings_for_preamble_duplicate_title_and_unresolved_dialogue() -> None:
    result = analyze_chapters(
        "作品名称：测试\n"
        "第一章 相遇\n正文一。\n"
        "第二章 相遇\n正文二。\n"
        "第三章 未知声音\n“不要回头。”"
    )

    assert {issue["code"] for issue in result.issues} == {
        "preamble_ignored",
        "duplicate_chapter_title",
        "manual_character_review_required",
    }


def test_rejects_missing_heading_with_structured_code() -> None:
    with pytest.raises(LocalPipelineError) as error:
        parse_chapters("只有正文，没有章节标题。")

    assert error.value.code == "chapter_heading_not_found"


def test_rejects_nul_control_character_with_structured_code() -> None:
    with pytest.raises(LocalPipelineError) as error:
        parse_chapters("第一章 一\n正文。\0\n第二章 二\n正文。\n第三章 三\n正文。")

    assert error.value.code == "invalid_control_character"


def test_rejects_other_invalid_control_character() -> None:
    result = analyze_chapters("第一章 一\n正文。\x01\n第二章 二\n正文。\n第三章 三\n正文。")

    assert result.eligible is False
    assert result.issues[0]["code"] == "invalid_control_character"


def test_rejects_source_over_character_limit() -> None:
    with pytest.raises(LocalPipelineError) as error:
        parse_chapters(
            "第一章 一\n"
            + "甲" * 100_000
            + "\n第二章 二\n正文。\n第三章 三\n正文。"
        )

    assert error.value.code == "source_text_too_long"


def test_special_characters_are_preserved_in_traceable_output() -> None:
    result = generate_local_screenplay(
        "第一章 符号\n林夏写下：key: value # test & * | >。门牌上画着 ☂️。\n"
        "第二章 连字符\n---不是章节标题---\n正文继续。\n"
        "第三章 结束\n她保存了 100% 的证据。"
    )

    all_evidence = " ".join(
        event["evidence"]["quote"] for event in result.screenplay["narrative_events"]
    )
    assert "# test & * | >" in all_evidence
    assert validate_screenplay(result.screenplay, result.source_texts)["passed"] is True
    assert "林夏写下" not in {
        character["name"] for character in result.screenplay["story_bible"]["characters"]
    }


def test_returns_warning_for_duplicate_chapter_number() -> None:
    result = analyze_chapters(
        "第一章 开始\n正文一。\n"
        "第一章 继续\n正文二。\n"
        "第三章 结束\n正文三。"
    )

    assert "duplicate_chapter_number" in {issue["code"] for issue in result.issues}


def test_normalizes_chinese_and_arabic_duplicate_chapter_number() -> None:
    result = analyze_chapters(
        "第一章 开始\n正文一。\n"
        "第1章 继续\n正文二。\n"
        "第三章 结束\n正文三。"
    )

    assert "duplicate_chapter_number" in {issue["code"] for issue in result.issues}


def test_does_not_invent_objects_or_partial_speaker_names_as_characters() -> None:
    result = generate_local_screenplay(
        "第一章 一\n大门打开。林夏回答。\n"
        "第二章 二\n窗户打开。林夏低声说。\n"
        "第三章 三\n铁门打开。"
    )

    assert result.screenplay["story_bible"]["characters"] == []


def test_does_not_reuse_location_from_another_chapter() -> None:
    result = generate_local_screenplay(
        "第一章 一\n林夏说：“出发。”随后来到废弃车站。\n"
        "第二章 二\n雨停了。\n"
        "第三章 三\n天亮了。"
    )
    locations = {
        item["id"]: item["name"] for item in result.screenplay["story_bible"]["locations"]
    }
    scene_location_names = [
        locations[scene["heading"]["location_id"]]
        for scene in result.screenplay["screenplay"]["scenes"]
    ]

    assert scene_location_names == ["未指定场景", "未指定场景", "未指定场景"]


def test_conservative_speaker_rules_do_not_invent_common_false_names() -> None:
    result = generate_local_screenplay(
        "第一章 一\n她低声说：“别动。”\n"
        "第二章 二\n然后林夏说：“一。”这时陈默问道：“二？”\n"
        "第三章 三\n林夏对陈默说：“三。”"
    )

    assert result.screenplay["story_bible"]["characters"] == []


def test_conservative_location_rules_do_not_treat_exists_at_home_as_location() -> None:
    result = generate_local_screenplay(
        "第一章 一\n秘密存在家族的旧信中。\n"
        "第二章 二\n答案存在家族档案里。\n"
        "第三章 三\n传闻存在家族历史中。"
    )

    assert [item["name"] for item in result.screenplay["story_bible"]["locations"]] == [
        "未指定场景"
    ]


def test_accepts_exact_character_limit() -> None:
    prefix = "第一章 一\n正文一。\n第二章 二\n正文二。\n第三章 三\n"
    novel = prefix + "甲" * (100_000 - len(prefix))

    result = generate_local_screenplay(novel)

    assert len(result.screenplay["source"]["chapters"]) == 3
    assert validate_screenplay(result.screenplay, result.source_texts)["passed"] is True


def test_parse_preserves_over_one_hundred_chapters_but_blocks_generation() -> None:
    novel = "\n".join(f"第{i}章 标题\n正文。" for i in range(1, 102))

    result = analyze_chapters(novel)

    assert result.eligible is False
    assert len(result.chapters) == 101
    assert "chapter_count_too_high" in {issue["code"] for issue in result.issues}
    with pytest.raises(LocalPipelineError, match="最多生成 100 个章节"):
        generate_local_screenplay(novel)
