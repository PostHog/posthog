"""The pull request linking rule, in the words every writer of a report summary reads.

Two surfaces name a pull request in prose a person reads: the pipeline's presentation turn
(`report_generation/research.py`), which writes the report title and summary, and a report-channel
scout writing its own summary (`scout_harness/prompt.py`). Only the scout side carried a linking
rule, and that one is scoped to PostHog entities, so a pull request reached the reader as a bare
number. A number costs the reader a GitHub search, and a number from another repository reads as
this one's and sends them to the wrong pull request.

Kept dependency-light for the same reason as `report_actionability.py`, because it loads with the
signals models. It is also rendered into the scout harness prompt, so an edit here moves
`HARNESS_PROMPT_VERSION` through `scout_harness.prompt._RENDERED_IMPORTS`.
"""

from __future__ import annotations

PULL_REQUEST_LINK_RULE = """- **A pull request or issue is a markdown link too, and names its repository.** Write `[#1234](https://github.com/PostHog/posthog/pull/1234)`, taking the URL from the `url` field a `gh pr view --json url` or `gh issue view --json url` call returned. A bare number reads as the repository the report is about, so a number from a different repository sends the reader to the wrong pull request: put the repository in the anchor text whenever it differs, as in `[PostHog/posthog-js#412](<url>)`. Never build the URL around a number you retyped. When no call verified a URL, keep the bare number and say plainly that the reference is unverified rather than inventing a link."""
