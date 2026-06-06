"""Generate a traceable screenplay with deterministic local rules only."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass


MIN_CHAPTERS = 3
MAX_SOURCE_CHARACTERS = 100_000
SUMMARY_LIMIT = 80
EVIDENCE_LIMIT = 200

CHAPTER_HEADING_RE = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]+)?(?P<title>"
    r"第[ \t]*[零〇一二三四五六七八九十百千万两\d]+[ \t]*章(?:[ \t　:：.-]+[^\r\n]+)?"
    r"|Chapter[ \t]+\d+(?:[ \t　:：.-]+[^\r\n]+)?"
    r")[ \t]*$"
)
CHAPTER_PREFIX_RE = re.compile(
    r"(?i)^(?:第[ \t]*[零〇一二三四五六七八九十百千万两\d]+[ \t]*章|Chapter[ \t]+\d+)"
    r"[ \t　:：.-]*"
)
SENTENCE_RE = re.compile(r"[^。！？!?\r\n]+[。！？!?]?")
INVALID_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class LocalPipelineError(ValueError):
    """Raised when local generation cannot satisfy the product contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Chapter:
    """A parsed source chapter whose text is used for hashing and evidence."""

    id: str
    order: int
    title: str
    text: str


@dataclass(frozen=True)
class PipelineResult:
    """Complete local generation result and exact imported source texts."""

    screenplay: dict
    source_texts: dict[str, str]
    issues: tuple[dict, ...]


@dataclass(frozen=True)
class ChapterParseResult:
    """Parsed chapters plus non-blocking source quality warnings."""

    chapters: tuple[Chapter, ...]
    issues: tuple[dict, ...]
    eligible: bool = True
    preamble: str = ""
    total_characters: int = 0


def _normalize_source(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, limit: int) -> str:
    text = _clean_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _chapter_subject(title: str) -> str:
    """Return the human title after the chapter number for duplicate warnings."""
    return CHAPTER_PREFIX_RE.sub("", title).strip() or title


def _chapter_number_key(title: str) -> str:
    """Return a normalized heading number token for duplicate warnings."""
    match = re.match(
        r"(?i)^(?:第[ \t]*(?P<cn>[零〇一二三四五六七八九十百千万两\d]+)[ \t]*章"
        r"|Chapter[ \t]+(?P<en>\d+))",
        title,
    )
    if not match:
        return title.lower()
    token = match.group("cn") or match.group("en")
    normalized = token.replace("〇", "零").replace("两", "二")
    if normalized.isdigit():
        return str(int(normalized))
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = section = number = 0
    for character in normalized:
        if character in digits:
            number = digits[character]
        elif character in units:
            unit = units[character]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = number = 0
            else:
                section += (number or 1) * unit
                number = 0
    return str(total + section + number)


def _issue(code: str, message: str, related_ids: list[str] | None = None) -> dict:
    return {
        "code": code,
        "severity": "error",
        "message": message,
        "related_ids": related_ids or [],
    }


def analyze_chapters(novel_text: str) -> ChapterParseResult:
    """Parse chapter headings and return warnings without silently dropping input."""
    if not isinstance(novel_text, str) or not novel_text.strip():
        return ChapterParseResult(
            chapters=(),
            issues=(_issue("chapter_heading_not_found", "小说文本不能为空。"),),
            eligible=False,
            total_characters=0,
        )

    source = _normalize_source(novel_text)
    if len(source) > MAX_SOURCE_CHARACTERS:
        return ChapterParseResult(
            chapters=(),
            issues=(
                _issue(
                    "source_text_too_long",
                    f"小说文本不能超过 {MAX_SOURCE_CHARACTERS} 个字符。",
                ),
            ),
            eligible=False,
            total_characters=len(source),
        )
    if INVALID_CONTROL_RE.search(source):
        return ChapterParseResult(
            chapters=(),
            issues=(
                _issue(
                    "invalid_control_character",
                    "小说文本包含不支持的控制字符。",
                ),
            ),
            eligible=False,
            total_characters=len(source),
        )

    matches = list(CHAPTER_HEADING_RE.finditer(source))
    if not matches:
        return ChapterParseResult(
            chapters=(),
            issues=(_issue("chapter_heading_not_found", "未识别到支持的章节标题。"),),
            eligible=False,
            total_characters=len(source),
        )

    issues: list[dict] = []
    preamble = source[: matches[0].start()].strip()
    if preamble:
        issues.append(
            {
                "code": "preamble_ignored",
                "severity": "warning",
                "message": "第一章前的内容未参与生成。",
                "related_ids": [],
            }
        )

    chapters: list[Chapter] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        body = source[body_start:body_end].strip()
        chapters.append(
            Chapter(
                id=f"chapter_{index + 1:03d}",
                order=index + 1,
                title=match.group("title").strip(),
                text=body,
            )
        )
        if not body:
            issues.append(
                _issue(
                    "empty_chapter",
                    f"章节“{match.group('title').strip()}”没有正文。",
                    [f"chapter_{index + 1:03d}"],
                )
            )

    if len(chapters) < MIN_CHAPTERS:
        issues.append(
            _issue(
                "chapter_count_too_low",
                f"至少需要 {MIN_CHAPTERS} 个章节，当前仅识别到 {len(chapters)} 个。",
                [chapter.id for chapter in chapters],
            )
        )

    title_counts = Counter(_chapter_subject(chapter.title) for chapter in chapters)
    for title, count in title_counts.items():
        if count > 1:
            issues.append(
                {
                    "code": "duplicate_chapter_title",
                    "severity": "warning",
                    "message": f"章节标题重复：{title}",
                    "related_ids": [
                        chapter.id
                        for chapter in chapters
                        if _chapter_subject(chapter.title) == title
                    ],
                }
            )

    number_counts = Counter(_chapter_number_key(chapter.title) for chapter in chapters)
    for number, count in number_counts.items():
        if count > 1:
            issues.append(
                {
                    "code": "duplicate_chapter_number",
                    "severity": "warning",
                    "message": f"章节编号重复：{number}",
                    "related_ids": [
                        chapter.id
                        for chapter in chapters
                        if _chapter_number_key(chapter.title) == number
                    ],
                }
            )

    unresolved_quote_re = re.compile(r"[“\"][^”\"\r\n]+[”\"]")
    for chapter in chapters:
        if unresolved_quote_re.search(chapter.text):
            issues.append(
                {
                    "code": "manual_character_review_required",
                    "severity": "warning",
                    "message": f"{chapter.title} 包含对白，本地规则模式不猜测人物身份。",
                    "related_ids": [chapter.id],
                }
            )
    eligible = not any(issue["severity"] == "error" for issue in issues)
    return ChapterParseResult(
        chapters=tuple(chapters),
        issues=tuple(issues),
        eligible=eligible,
        preamble=preamble,
        total_characters=sum(len(chapter.text) for chapter in chapters),
    )


def parse_chapters(novel_text: str) -> list[Chapter]:
    """Return parsed chapters for callers that do not need warnings."""
    result = analyze_chapters(novel_text)
    if not result.eligible:
        first_error = next(issue for issue in result.issues if issue["severity"] == "error")
        raise LocalPipelineError(first_error["code"], first_error["message"])
    return list(result.chapters)


def _sentences(text: str) -> list[tuple[str, int, int]]:
    sentences: list[tuple[str, int, int]] = []
    for match in SENTENCE_RE.finditer(text):
        raw = match.group(0)
        left_trim = len(raw) - len(raw.lstrip())
        quote = raw.strip()
        if not quote:
            continue
        start = match.start() + left_trim
        if len(quote) > EVIDENCE_LIMIT:
            quote = quote[:EVIDENCE_LIMIT]
        sentences.append((quote, start, start + len(quote)))
    return sentences


def _select_evidence(chapter: Chapter) -> tuple[str, int, int]:
    candidates = _sentences(chapter.text)
    if not candidates:
        quote = chapter.text[:EVIDENCE_LIMIT]
        return quote, 0, len(quote)
    return max(candidates, key=lambda item: (len(item[0]), -item[1]))


def _extract_characters(chapters: list[Chapter]) -> tuple[list[dict], dict[str, str]]:
    """Avoid fabricating identities when deterministic rules cannot prove them."""
    return [], {}


def _extract_locations(chapters: list[Chapter]) -> tuple[list[dict], dict[str, str]]:
    """Use an explicit placeholder instead of guessing a source location."""
    return (
        [
            {
                "id": "location_001",
                "name": "未指定场景",
                "description": "本地规则模式不猜测地点，由作者确认或交给 AI 模式分析。",
            }
        ],
        {"未指定场景": "location_001"},
    )


def _event_for_chapter(chapter: Chapter) -> dict:
    quote, start, end = _select_evidence(chapter)
    return {
        "id": f"event_{chapter.order:03d}",
        "chapter_id": chapter.id,
        "summary": _truncate(quote, SUMMARY_LIMIT),
        "importance": "critical" if chapter.order == 1 else "major",
        "evidence": {
            "quote": quote,
            "start_char": start,
            "end_char": end,
        },
    }


def _scene_for_chapter(
    chapter: Chapter,
    event: dict,
) -> dict:
    beats = [{"type": "action", "text": event["evidence"]["quote"]}]

    return {
        "id": f"scene_{chapter.order:03d}",
        "order": chapter.order,
        "heading": {
            "int_ext": "INT_EXT",
            "location_id": "location_001",
            "time_of_day": "未指定",
        },
        "purpose": f"改编并保留{chapter.title}的关键事件。",
        "character_ids": [],
        "beats": beats,
        "traceability": {
            "origin": "source_adaptation",
            "source_chapter_ids": [chapter.id],
            "source_event_ids": [event["id"]],
            "adaptation_actions": [
                {
                    "type": "rewrite",
                    "description": "将章节关键叙述转换为可表演的场次内容。",
                    "rationale": "在不新增剧情事件的前提下形成结构化剧本初稿。",
                }
            ],
        },
    }


def generate_local_screenplay(novel_text: str, title: str = "本地规则改编") -> PipelineResult:
    """Convert a multi-chapter novel into a complete, traceable screenplay."""
    parse_result = analyze_chapters(novel_text)
    if not parse_result.eligible:
        first_error = next(
            issue for issue in parse_result.issues if issue["severity"] == "error"
        )
        raise LocalPipelineError(first_error["code"], first_error["message"])
    chapters = list(parse_result.chapters)
    characters, _ = _extract_characters(chapters)
    locations, _ = _extract_locations(chapters)
    events = [_event_for_chapter(chapter) for chapter in chapters]
    scenes = [
        _scene_for_chapter(chapter, event)
        for chapter, event in zip(chapters, events)
    ]
    source_texts = {chapter.id: chapter.text for chapter in chapters}
    chapter_summaries = [_truncate(_select_evidence(chapter)[0], SUMMARY_LIMIT) for chapter in chapters]

    screenplay = {
        "schema_version": "1.0.0",
        "project": {
            "id": "project_local_rules",
            "title": title.strip() or "本地规则改编",
            "logline": f"围绕{chapter_summaries[0]}展开的多章节改编。",
            "genre": ["剧情"],
            "format": "short_series",
            "language": "zh-CN",
            "generation": {
                "provider": "local-rules",
                "model": "",
                "mode": "local_rules",
                "fallback_reason": "",
            },
        },
        "adaptation_control": {
            "fidelity": "faithful",
            "target_scene_count": len(scenes),
            "focus": ["visual_action", "dialogue"],
            "must_keep_event_ids": [events[0]["id"]],
            "allow_new_events": False,
            "forbidden_changes": ["不新增原文不存在的剧情事件"],
        },
        "source": {
            "chapter_count": len(chapters),
            "total_characters": sum(len(chapter.text) for chapter in chapters),
            "chapters": [
                {
                    "id": chapter.id,
                    "order": chapter.order,
                    "title": chapter.title,
                    "summary": summary,
                    "content_sha256": hashlib.sha256(chapter.text.encode("utf-8")).hexdigest(),
                }
                for chapter, summary in zip(chapters, chapter_summaries)
            ],
        },
        "story_bible": {
            "premise": f"{chapter_summaries[0]}，故事随后跨越{len(chapters)}个章节继续发展。",
            "characters": characters,
            "locations": locations,
        },
        "narrative_events": events,
        "screenplay": {
            "synopsis": " ".join(chapter_summaries),
            "scenes": scenes,
        },
    }
    return PipelineResult(
        screenplay=screenplay,
        source_texts=source_texts,
        issues=parse_result.issues,
    )
