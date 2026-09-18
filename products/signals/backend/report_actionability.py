"""The actionability contract, in the words every judge of it reads.

Two paths set a report's `ActionabilityChoice` (`artefact_schemas.py`): the pipeline's research
agent judges a clustered report after investigating it, and a report-channel scout makes the call
itself on the report it authored. Both decide the status the report is born at, so both apply these
criteria. A surface that carries only the status mapping produces the drift this text guards
against, because a report whose root cause is still open reads as `requires_human_input` and parks
in PENDING_INPUT the work a coding agent had a clear starting point for.

Kept dependency-light for the same reason as `report_prompts.py`, because it loads with the signals
models. It is also rendered into the scout harness prompt, so an edit here moves
`HARNESS_PROMPT_VERSION` through `scout_harness.prompt._RENDERED_IMPORTS`.
"""

from __future__ import annotations

ACTIONABILITY_CRITERIA = """1. **immediately_actionable** — A coding agent could take concrete, useful action right now. Examples: bug fixes, experiment reactions, feature flag cleanup, UX fixes, deep investigation with clear jumping-off points. An unknown root cause does not disqualify a report: when it names the evidence, the code surface, or a failure path someone can reproduce, the investigation is the action.
2. **requires_human_input** — A code change is plausible, but a person must first make a call only a person can make: a product decision, a trade-off between valid approaches, business context that is not in the data or the code. The input only counts if it's needed *for a code change* — if no answer would lead to code work, this is `not_actionable`. "Someone should look into this first" is not human input; that is the work itself.
3. **not_actionable** — No path to a code change exists (too vague, insufficient evidence, expected behavior, or the resolution lives entirely outside the codebase — e.g. a pricing/GTM/business call).

When in doubt between `immediately_actionable` and `requires_human_input`, choose `immediately_actionable`.
When in doubt between `requires_human_input` and `not_actionable`, choose `not_actionable`."""
