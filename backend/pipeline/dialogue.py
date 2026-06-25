"""Source dialogue extraction and retention helpers."""

from __future__ import annotations

import re
from typing import Any


QUOTE_RE = re.compile(r"[“\"『「](.*?)[”\"』」]", re.DOTALL)
SPEECH_MARKERS = (
    "说",
    "问",
    "道",
    "叫",
    "喊",
    "吼",
    "答",
    "笑",
    "骂",
    "喝",
    "嘀咕",
    "喃喃",
    "低声",
    "大声",
)


def normalize_dialogue_text(value: str) -> str:
    """Normalize dialogue for retention checks while preserving Chinese characters."""
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE).casefold()


def _looks_like_dialogue(quote: str, before: str, after: str) -> bool:
    stripped = quote.strip()
    if len(normalize_dialogue_text(stripped)) < 2:
        return False
    context = before[-16:] + after[:16]
    has_speech_context = any(marker in context for marker in SPEECH_MARKERS)
    has_sentence_punctuation = bool(re.search(r"[。！？!?，,；;：:…]", stripped))
    has_interactive_words = any(
        word in stripped
        for word in ("我", "你", "咱", "我们", "你们", "他妈", "啊", "呢", "吗", "吧", "呀")
    )
    return has_speech_context or has_sentence_punctuation or has_interactive_words or len(stripped) >= 12


def extract_source_dialogues(
    source_texts: dict[str, str],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Extract quoted source dialogue with chapter-local character positions."""
    dialogues: list[dict[str, Any]] = []
    for chapter_id, source_text in source_texts.items():
        chapter_count = 0
        for match in QUOTE_RE.finditer(source_text):
            quote_start, quote_end = match.span(1)
            quote = match.group(1).strip()
            before = source_text[max(0, match.start() - 24):match.start()]
            after = source_text[match.end():match.end() + 24]
            if not _looks_like_dialogue(quote, before, after):
                continue
            chapter_count += 1
            dialogues.append(
                {
                    "dialogue_id": f"{chapter_id}_dialogue_{chapter_count:03d}",
                    "chapter_id": chapter_id,
                    "text": quote,
                    "start_char": quote_start,
                    "end_char": quote_end,
                }
            )
            if limit is not None and len(dialogues) >= limit:
                return dialogues
    return dialogues


def screenplay_dialogue_texts(screenplay: dict) -> list[str]:
    return [
        beat.get("text", "")
        for scene in screenplay.get("screenplay", {}).get("scenes", [])
        for beat in scene.get("beats", [])
        if beat.get("type") == "dialogue"
    ]


def retained_source_dialogue_ids(
    source_dialogues: list[dict[str, Any]],
    screenplay: dict,
) -> set[str]:
    generated_dialogues = [
        normalize_dialogue_text(text) for text in screenplay_dialogue_texts(screenplay)
    ]
    retained: set[str] = set()
    for dialogue in source_dialogues:
        source_text = normalize_dialogue_text(dialogue["text"])
        if not source_text:
            continue
        for generated_text in generated_dialogues:
            if not generated_text:
                continue
            if source_text in generated_text or (
                len(source_text) >= 4 and generated_text in source_text
            ):
                retained.add(dialogue["dialogue_id"])
                break
    return retained
