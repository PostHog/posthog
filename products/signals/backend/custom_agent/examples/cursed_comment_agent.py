"""Realistic `CustomSignalAgent` example: finds the most cursed comment in a repo.

Unlike ``cookie_poem_agent`` (which registers everything statically), this agent does
real work against a real codebase and lets the default resolvers do their job:

- It runs against a target repository (explicit ``owner/repo`` or free-form selection),
  so the sandbox clones the repo and the agent can ``grep``/``rg``/``gh`` through it.
- ``run()`` only registers ``title`` and ``description`` from the agent's research.
  ``actionability``, ``priority``, and ``assignees`` are left unregistered, so the base
  class resolves them **agentically** from the in-session conversation — the same path a
  real custom agent would use.

This module defines only the agent class and its default prompt. Temporal wiring lives in
the ``run_custom_agent_example`` management command — the activity dynamically imports agent
modules via ``import_agent_class``, and pulling the Temporal layer in at module load time can
hit partial-load ``ImportError``s.

Run via the management command::

    # Free-form repo selection from the team's connected repos
    python manage.py run_custom_agent_example --agent cursed_comment --team-id 1

    # Against an explicit repository
    python manage.py run_custom_agent_example --agent cursed_comment --team-id 1 --repository PostHog/posthog
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from products.signals.backend.custom_agent import CustomSignalAgent

DEFAULT_PROMPT = (
    "Hunt through this repository for the single most cursed code comment — the kind that makes "
    "an engineer laugh nervously and then get worried. Think ominous warnings ('do not touch', "
    "'here be dragons', 'I am so sorry'), confessions of hacks, load-bearing TODOs/FIXMEs, "
    "comments that admit the code is wrong but ships anyway, or anything that hints at a real "
    "latent bug or maintenance trap. Report the best one with enough context to act on it."
)


class CursedComment(BaseModel):
    """The agent's structured finding for a single cursed comment."""

    headline: str = Field(
        max_length=120,
        description="Short, punchy title naming the cursed comment (no file path).",
    )
    file_path: str = Field(description="Repo-relative path to the file containing the comment.")
    line: int | None = Field(default=None, description="1-based line number of the comment, or null if unknown.")
    comment_text: str = Field(description="The verbatim cursed comment, trimmed to the relevant line(s).")
    why_cursed: str = Field(
        description="Why this comment is cursed — the risk, smell, or latent bug it hints at, grounded in the code around it.",
    )


class CursedCommentAgent(CustomSignalAgent):
    """Searches a real repository for its most cursed comment and files a report on it."""

    @classmethod
    def identifier(cls) -> tuple[str, str]:
        return "signals", "cursed_comment"

    async def run(self) -> bool:
        finding = await self.send(
            "Search the cloned repository for the most cursed code comment you can find. Use shell tools "
            "against the checkout — `rg`/`grep` for markers like `HACK`, `FIXME`, `XXX`, `do not`, `dragons`, "
            "`I'm sorry`, `god help`, `temporary`, `for now`, etc. — then open the surrounding lines to judge "
            "which is genuinely the worst. Pick the single best one and report its file path, line number, "
            "the verbatim comment text, and why it's cursed (the real risk it hints at, not just the vibes).",
            CursedComment,
            label="cursed_comment_search",
        )

        self.register_title(f"Cursed comment: {finding.headline}")

        location = f"`{finding.file_path}`"
        if finding.line is not None:
            location += f" (line {finding.line})"
        self.register_description(
            f"**Where:** {location}\n\n"
            f"**The comment:**\n\n```\n{finding.comment_text.strip()}\n```\n\n"
            f"**Why it's cursed:** {finding.why_cursed}"
        )

        # actionability, priority, and assignees are intentionally left unregistered so the
        # base class resolves them agentically from the research conversation above.
        return True
