"""Linking rules shared by the two surfaces that write a report title and summary.

The pipeline's presentation turn (`report_generation/research.py`) and a report-channel scout
(`scout_harness/prompt.py`) both write prose a person reads, so both need the same wording. A
second copy drifts, and the reader then gets a pull request linked on one report and left as a
bare number on the next.

Kept dependency-light for the same reason as `report_actionability.py`, because it loads with the
signals models. It is also rendered into the scout harness prompt, so an edit here moves
`HARNESS_PROMPT_VERSION` through `scout_harness.prompt._RENDERED_IMPORTS`.
"""

from __future__ import annotations

PULL_REQUEST_LINK_RULE = """- **A pull request or issue is a markdown link too, and names its repository.** Write `[#1234](https://github.com/PostHog/posthog/pull/1234)`, taking the URL from the `url` field a `gh pr view --json url` or `gh issue view --json url` call returned. A bare number reads as the repository the report is about, so a number from a different repository sends the reader to the wrong pull request: put the repository in the anchor text whenever it differs, as in `[PostHog/posthog-js#412](<url>)`. Never build the URL around a number you retyped. When no call verified a URL, keep the bare number and say plainly that the reference is unverified rather than inventing a link."""

PLAIN_TEXT_FIELDS_RULE = """- **A report `title` and the first line of its `summary` stay plain text.** The inbox renders the title as text and lifts the summary's first line out verbatim as the card headline, so a markdown link in either shows up as literal brackets beside a raw URL. Name the entity in words there, and link it where the body picks it up again."""
