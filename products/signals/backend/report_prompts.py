"""The prompts a report suggests its reader send about it (questions or next-step actions): bounds
and the refusals a set has to pass.

A suggested prompt is part of a report's content, not an entry in its log — it lives on
`SignalReport.suggested_prompts` alongside the summary it was written against, so it is replaced
with that summary rather than accumulating versions beside it. Kept out of `artefact_schemas.py` for
that reason, and kept as dependency-light as `report_charts.py` for the same one: it loads with the
signals models, so it must not drag `posthog.schema` onto every process's `django.setup()` path.

The authoring guidance is rendered into both the scout harness prompt and the pipeline's research
presentation prompt, so an edit here moves `HARNESS_PROMPT_VERSION` through
`scout_harness.prompt._RENDERED_IMPORTS`.
"""

from __future__ import annotations

from collections.abc import Sequence

# How many prompts one report may suggest. The inbox renders them as rows above a textarea the
# reader can still type into, so the set has to stay readable at a glance — past a handful, picking
# one costs more than writing the prompt they already had in mind.
MAX_SUGGESTED_PROMPTS = 3

# One prompt, in characters. A suggestion is a question or action request the reader clicks and can
# then extend in the textarea, not a brief, so the bound is about one long sentence.
MAX_SUGGESTED_PROMPT_LENGTH = 200


def normalize_suggested_prompts(prompts: Sequence[str]) -> list[str]:
    """The set as it should be stored: each prompt trimmed, blank ones dropped.

    Trailing whitespace on an LLM-authored string is both common and invisible, and it would
    otherwise make a re-send of the same set compare unequal to what is stored — which
    `set_report_suggested_prompts` reads as a real change and notifies the report's destination
    about. Dropping blanks keeps an empty string from rendering as a clickable row with nothing
    on it.
    """
    return [stripped for prompt in prompts if (stripped := prompt.strip())]


def suggested_prompts_batch_error(prompts: Sequence[str]) -> str | None:
    """Why a set of suggested prompts can't be stored, or None if it can.

    Whole-set checks decided from the payload alone, so a caller writing prompts from any entry
    point (the scout tools, the DRF view, persistence) refuses the same sets without restating the
    rules. Uniqueness matters because the inbox renders one row per prompt: two identical rows
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


def suggested_prompts_guidance(*, heading: str, field_location: str, whole_set_rule: str) -> str:
    """The authoring guidance for `suggested_prompts`, shared by the scout report tools and the
    pipeline's research presentation step so both channels write prompts to the same rules.

    The channels differ in the heading level of their prompt, in where the field sits, and in how a
    new set replaces the stored one, so the caller supplies those three parts.
    """
    return f"""{heading} Suggesting follow-up prompts

`suggested_prompts` {field_location} carries prompts the inbox offers above the report's `Ask AI` box: follow-up questions, and next-step actions the reader can send as a request. Clicking one fills the box with it, so the reader can send it as written or edit it first. Nothing is sent on the click. You did the research and know which threads you left open and what should happen next, so this hands the reader that knowledge instead of leaving them to invent a prompt from an empty box.

Optional, and worth it only when you can name a prompt worth an agent run. Write none rather than pad to the cap: an obvious prompt the reader would have typed anyway costs them a read and gains nothing, and a report with no suggestions looks exactly as it did before.

- **At most {MAX_SUGGESTED_PROMPTS}, each up to {MAX_SUGGESTED_PROMPT_LENGTH} characters.** They render as rows the reader scans before choosing, so three is a ceiling and one or two is the usual answer.
- **A prompt is a question or an action request, in the reader's words.** "Which customers are hitting this?" reads as a question they would ask; "Create the alert the report recommends, then mark this report resolved" reads as a request they would make. What does not work is machine-speak like "Analyze the affected cohort", which the reader has to translate before they can tell whether they want it.
- **Ask what your research left open, not what it already answered.** A question the summary answers wastes an agent run to restate the report. Good ones widen the finding (who else is affected, since when, what changed), test the hypothesis you could not, or ask for the next step you did not have the standing to take.
- **Offer the action your report recommends, so acting on it is one click.** The prompt is sent to an agent run that can investigate, carry out the report's recommendation, and work the report itself (its work log and its state). A good action prompt names the concrete work: "Create the alert the report recommends, then mark this report resolved". Fold in "mark this report resolved" only when the action completes in place — an action that lands as a pull request must not resolve the report, because a caller resolve closes the report's open PR and the merge resolves the report on its own. Suggest only actions your report's own recommendation makes concrete, and leave anything a human should weigh first (deleting data, changing a flag serving live traffic) as a question instead.
- **Each one stands alone.** The prompt goes to an agent that gets the report as context but not your run, so it must name what it is asking for rather than pointing at "the above" or "the second chart".
- **No two the same.** Duplicates are refused, and near-duplicates cost the reader a choice that is not one.
{whole_set_rule}

```json
[
  "Which teams are hitting this exception the most?",
  "Did the error rate change after the 18 June deploy?",
  "Add the null check the report recommends and open a pull request"
]
```"""
