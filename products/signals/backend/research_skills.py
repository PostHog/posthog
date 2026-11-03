from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from django.db.models import Q

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.permissions import get_authenticator_scopes, scopes_missing_after_legacy_fallback

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.agent_skills import AgentSkill, SkillNotFoundError, load_agent_skill_row
from products.signals.backend.models import SignalSourceConfig

if TYPE_CHECKING:
    from rest_framework.request import Request

    from products.signals.backend.temporal.types import SignalData

RESEARCH_SKILL_KEY = "research_skill"


def validate_research_skill_selection(config: dict, *, previous_config: dict, team: Team, request: Request) -> None:
    name = config.get(RESEARCH_SKILL_KEY)
    if name is not None and (not isinstance(name, str) or not name.strip() or name != name.strip() or len(name) > 64):
        raise ValidationError({"config": "research_skill must be a skill name or null."})
    if name == previous_config.get(RESEARCH_SKILL_KEY):
        return
    scopes = get_authenticator_scopes(request.successful_authenticator)
    if scopes is not None and scopes_missing_after_legacy_fallback(request, None, scopes, ["llm_skill:write"]):
        raise PermissionDenied("Changing the research skill requires llm_skill:write.")
    user = request.user
    if not isinstance(user, User) or not UserAccessControl(user=user, team=team).check_access_level_for_resource(
        "llm_skill", "editor"
    ):
        raise PermissionDenied("Changing the research skill requires editor access to skills.")
    if name is not None:
        try:
            load_agent_skill_row(team, name)
        except SkillNotFoundError:
            raise ValidationError(
                {"config": "Research skill not found. Select an active skill in this project."}
            ) from None


@frozen
class ResearchSource:
    product: str
    type: str

    @classmethod
    def for_signal(cls, signal: SignalData) -> ResearchSource:
        source_type = signal.source_type
        if signal.source_product == "session_replay" and source_type == "session_problem":
            source_type = "session_analysis_cluster"
        return cls(product=signal.source_product, type=source_type)


@frozen
class ResearchSkillBinding:
    source: ResearchSource
    team_id: int
    name: str
    version: int


@frozen
class ResearchSkills:
    by_source: dict[ResearchSource, AgentSkill]

    @classmethod
    def load(cls, team_id: int, signals: Sequence[SignalData]) -> ResearchSkills:
        sources = {ResearchSource.for_signal(signal) for signal in signals}
        if not sources:
            return cls(by_source={})
        team = Team.objects.get(id=team_id)
        query = Q()
        for source in sources:
            config_team_id = (
                team.parent_team_id or team.id
                if source.product == "signals_scout" and source.type == "cross_source_issue"
                else team.id
            )
            query |= Q(team_id=config_team_id, source_product=source.product, source_type=source.type)
        selected: dict[ResearchSource, AgentSkill] = {}
        for config in SignalSourceConfig.objects.filter(query).select_related("team"):
            name = config.config.get(RESEARCH_SKILL_KEY)
            if name:
                selected[ResearchSource(product=config.source_product, type=config.source_type)] = AgentSkill.load(
                    config.team, name
                )
        return cls(by_source=selected)

    @classmethod
    def from_bindings(cls, team_id: int, bindings: Sequence[ResearchSkillBinding]) -> ResearchSkills:
        team = Team.objects.get(id=team_id)
        selected: dict[ResearchSource, AgentSkill] = {}
        for binding in bindings:
            expected_team_id = (
                team.parent_team_id or team.id
                if binding.source == ResearchSource(product="signals_scout", type="cross_source_issue")
                else team.id
            )
            if binding.team_id != expected_team_id:
                raise ValueError("Research skill belongs to another project")
            selected[binding.source] = AgentSkill.load(
                Team.objects.get(id=binding.team_id), binding.name, version=binding.version
            )
        return cls(by_source=selected)

    def bindings(self, team_id: int) -> list[ResearchSkillBinding]:
        team = Team.objects.get(id=team_id)
        return [
            ResearchSkillBinding(
                source=source,
                team_id=(
                    team.parent_team_id or team.id
                    if source == ResearchSource(product="signals_scout", type="cross_source_issue")
                    else team.id
                ),
                name=skill.name,
                version=skill.version,
            )
            for source, skill in self.by_source.items()
        ]

    def for_signal(self, signal: SignalData) -> str:
        if not self.by_source:
            return ""
        skill = self.by_source.get(ResearchSource.for_signal(signal))
        if skill is None:
            return "\n\n## Source research skill\n\nNo custom skill applies to this signal. Use the default research protocol."
        return (
            "\n\n## Source research skill\n\n"
            "Apply this customer skill to this source's evidence and findings, including the final assessment. "
            "Other sources keep their own instructions. The research protocol, evidence requirements, "
            "permissions, and structured output contract still apply. Do not follow scheduled scout routines "
            "or create another report. Investigate the signal supplied in this turn.\n\n"
            + skill.research_instructions()
        )


NO_RESEARCH_SKILLS = ResearchSkills(by_source={})
