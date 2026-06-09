"""ApiDeprecationAgent — the agentic changelog-research stage.

Takes the deterministic detector's pin inventory and, per pin, researches the vendor's real changelog
(``research.build_research_prompt`` → ``send`` → cited ``ResearchedDeprecation``), then emits one
inbox report for the deprecations it could actually cite. This is where dates and the
mechanical/structural call come from — never a seeded table.

It runs in the Signals custom-agent sandbox (web/MCP tools, repo cloned). Construct it with the pins
produced by ``scanner.scan_repo`` against a checkout of the same ``repository``.
"""

from __future__ import annotations

from datetime import date

from posthog.models import Team

from products.signals.backend.api_deprecation.emit import render_report
from products.signals.backend.api_deprecation.research import RESEARCH_SYSTEM_NOTE, build_research_prompt
from products.signals.backend.api_deprecation.schema import Pin, ResearchedDeprecation
from products.signals.backend.custom_agent.base import CustomSignalAgent


class ApiDeprecationAgent(CustomSignalAgent):
    """Researches each detected version pin against its vendor changelog and reports the cited stale ones."""

    def __init__(
        self,
        *,
        team: Team,
        pins: list[Pin],
        repository: str,
        initial_prompt: str = RESEARCH_SYSTEM_NOTE,
        user_id: int | None = None,
        model: str | None = None,
        today: date | None = None,
    ) -> None:
        super().__init__(
            team=team,
            initial_prompt=initial_prompt,
            repository=repository,
            user_id=user_id,
            model=model,
        )
        self._pins = [p for p in pins if not p.is_test_file]
        self._today = today or date.today()
        # The deprecated findings this run produced (cited). Read by the dispatch stage after start().
        self.findings: list[ResearchedDeprecation] = []

    @classmethod
    def identifier(cls) -> tuple[str, str]:
        return ("signals", "api_deprecation")

    async def run(self) -> bool:
        findings: list[ResearchedDeprecation] = []
        for pin in self._pins:
            result = await self.send(
                build_research_prompt(pin),
                ResearchedDeprecation,
                label=f"research_{pin.vendor}_{pin.pinned_version}",
            )
            if result.is_deprecated:
                findings.append(result)

        self.findings = findings
        components = render_report(findings, self._today)
        if components is None:
            return False  # nothing citable to report — a valid outcome

        self.register_title(components.title)
        self.register_description(components.description)
        self.register_actionability(components.actionability)
        self.register_priority(components.priority)
        self.register_assignees([])  # no auto-PR in this milestone; dispatch is added explicitly in M2
        return True
