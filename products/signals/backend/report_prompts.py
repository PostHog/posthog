"""The questions a report suggests its reader ask about it: bounds and the refusals a set has to pass.

A suggested prompt is part of a report's content, not an entry in its log — it lives on
`SignalReport.suggested_prompts` alongside the summary it was written against, so it is replaced
with that summary rather than accumulating versions beside it. Kept out of `artefact_schemas.py` for
that reason, and kept as dependency-light as `report_charts.py` for the same one: it loads with the
signals models, so it must not drag `posthog.schema` onto every process's `django.setup()` path.
"""

from __future__ import annotations

from collections.abc import Sequence

# How many questions one report may suggest. The inbox renders them as rows above a textarea the
# reader can still type into, so the set has to stay readable at a glance — past a handful, picking
# one costs more than writing the question they already had in mind.
MAX_SUGGESTED_PROMPTS = 3

# One question, in characters. A suggestion is a question the reader clicks and can then extend in
# the textarea, not a brief, so the bound is about one long sentence.
MAX_SUGGESTED_PROMPT_LENGTH = 200


def normalize_suggested_prompts(prompts: Sequence[str]) -> list[str]:
    """The set as it should be stored: each question trimmed, blank ones dropped.

    Trailing whitespace on an LLM-authored string is both common and invisible, and it would
    otherwise make a re-send of the same set compare unequal to what is stored — which
    `set_report_suggested_prompts` reads as a real change and notifies the report's destination
    about. Dropping blanks keeps an empty string from rendering as a clickable row with no question
    on it.
    """
    return [stripped for prompt in prompts if (stripped := prompt.strip())]


def suggested_prompts_batch_error(prompts: Sequence[str]) -> str | None:
    """Why a set of suggested questions can't be stored, or None if it can.

    Whole-set checks decided from the payload alone, so a caller writing prompts from any entry
    point (the scout tools, the DRF view, persistence) refuses the same sets without restating the
    rules. Uniqueness matters because the inbox renders one row per question: two identical rows
    read as a rendering bug and cost the reader a choice that isn't one.
    """
    if len(prompts) > MAX_SUGGESTED_PROMPTS:
        return f"a report accepts at most {MAX_SUGGESTED_PROMPTS} suggested prompts ({len(prompts)})"
    for prompt in prompts:
        if len(prompt) > MAX_SUGGESTED_PROMPT_LENGTH:
            return f"a suggested prompt exceeds {MAX_SUGGESTED_PROMPT_LENGTH} characters ({len(prompt)})"
    if len(set(prompts)) != len(prompts):
        return "suggested prompts must be unique"
    return None
