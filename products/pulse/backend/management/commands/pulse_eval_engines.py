"""Side-by-side eval: an agent-written brief vs a freshly computed baseline
(gather + synthesize) for the same team. Human-judged; spec open question 6.

Deliberately does NOT run a sandbox itself (that needs Modal credentials and real
spend): it renders an agent-written brief next to a fresh baseline over the same
sources, so a human judge compares like against like.
"""

import asyncio
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.pulse.backend.generation.synthesize import synthesize_brief
from products.pulse.backend.models import ProductBrief
from products.pulse.backend.sources.base import SourceItem
from products.pulse.backend.sources.registry import get_sources


class Command(BaseCommand):
    help = "Render an agent-generated brief next to a baseline synthesize-engine brief for the same team."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--brief-id", type=str, required=True, help="An agent-engine ProductBrief id.")

    def handle(self, *args: Any, **options: Any) -> None:
        brief = (
            ProductBrief.objects.for_team(options["team_id"])
            .select_related("team__organization", "created_by", "config")
            .filter(id=options["brief_id"])
            .first()
        )
        if brief is None:
            raise CommandError("Brief not found for this team.")
        if brief.agent_session_ref is None:
            raise CommandError("Brief was not written by the agent engine (no agent_session_ref).")
        if brief.created_by is None:
            raise CommandError("Brief has no creating user; the baseline LLM call needs attribution.")

        items: list[SourceItem] = []
        for source in get_sources():
            items.extend(source.gather(brief.team, brief.config, brief.period_days))
        baseline = asyncio.run(
            synthesize_brief(
                team=brief.team,
                user=brief.created_by,
                config=brief.config,
                items=items,
                period_days=brief.period_days,
                # Bare baseline: the agent mission carries neither accountability nor goal
                # framing yet, so the comparison stays like-for-like.
                status_lines=[],
                goal_status=None,
            )
        )

        self.stdout.write(f"=== AGENT (brief {brief.id}, session {brief.agent_session_ref}) ===")
        for section in brief.sections:
            self.stdout.write(f"[{section.get('confidence')}] {section.get('title')}\n{section.get('markdown')}\n")
        self.stdout.write("=== BASELINE (fresh synthesize over the same sources) ===")
        for out_section in baseline.sections:
            self.stdout.write(f"[{out_section.confidence}] {out_section.title}\n{out_section.markdown}\n")
        self.stdout.write(f"counts: agent sections={len(brief.sections)} baseline sections={len(baseline.sections)}")
