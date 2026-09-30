"""Checks the LLM output must pass before it is shown. The draft is the fallback when it does not."""

import re
from typing import Any

from .content import BriefingContent
from .fact_sheet import FactSheet

MAX_WORDS = 130
MAX_LINK_WORDS = 8
MAX_LABEL_WORDS = 6
MAX_SIGNAL_CHARS = 40
_NUMBER = re.compile(r"\d[\d,]*\.?\d*")
_DASHES = ("—", "–")


def _numbers(value: Any, out: set[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        out.add(abs(float(value)))
    elif isinstance(value, dict):
        for inner in value.values():
            _numbers(inner, out)
    elif isinstance(value, list):
        for inner in value:
            _numbers(inner, out)
    elif isinstance(value, str):
        for match in _NUMBER.findall(value):
            out.add(float(match.replace(",", "")))


def _backed(number: float, known: set[float]) -> bool:
    return any(abs(number - value) < 0.51 for value in known)


def check_content(fact_sheet: FactSheet, content: BriefingContent) -> list[str]:
    """Every rule the output breaks, or an empty list when it passes."""
    problems: list[str] = []
    text_keys = [item.key for item in fact_sheet.text_items]
    top_key = next((item.key for item in fact_sheet.items if item.top), None)
    known: set[float] = set()
    _numbers(fact_sheet.model_dump(mode="json"), known)

    linked: list[str] = []
    highlighted: list[str | None] = []
    words = 0
    texts = [content.headline]
    if not texts[0]:
        problems.append("headline is empty")
    for paragraph in content.paragraphs:
        for segment in paragraph:
            text = segment.text
            texts.append(text)
            words += len(text.split())
            if segment.item_key:
                linked.append(segment.item_key)
                if not text[:1].isalnum():
                    problems.append(f"link does not start with a word: {text!r}")
                if len(text.split()) > MAX_LINK_WORDS:
                    problems.append(f"link has more than {MAX_LINK_WORDS} words: {text!r}")
            if segment.highlight:
                highlighted.append(segment.item_key)
    for key in text_keys:
        if linked.count(key) != 1:
            problems.append(f"item {key} is linked {linked.count(key)} times, expected once")
    for key in set(linked) - set(text_keys):
        problems.append(f"link to an item that is not in the text: {key}")
    if top_key is not None and highlighted != [top_key]:
        problems.append(f"only {top_key} may be highlighted, got {highlighted}")
    if words > MAX_WORDS:
        problems.append(f"paragraphs have {words} words, the limit is {MAX_WORDS}")

    for item in fact_sheet.items:
        label = content.labels.get(item.key, "")
        signal = content.signals.get(item.key, "")
        if not label or len(label.split()) > MAX_LABEL_WORDS:
            problems.append(f"label for {item.key} is missing or longer than {MAX_LABEL_WORDS} words")
        if not signal or len(signal) > MAX_SIGNAL_CHARS:
            problems.append(f"signal for {item.key} is missing or longer than {MAX_SIGNAL_CHARS} characters")
        texts += [label, signal]

    for text in texts:
        if any(dash in text for dash in _DASHES):
            problems.append(f"em or en dash in {text!r}")
        for match in _NUMBER.findall(text):
            if not _backed(float(match.replace(",", "")), known):
                problems.append(f"number {match} in {text!r} is not in the fact sheet")
    return problems
