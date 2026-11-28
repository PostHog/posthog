"""What one viewer may see of the flags, broadcasts, surveys and insights that releases link.

The release API and the release work thread both build their `LinkLookups` here, so the two hide the same things.
"""

from collections.abc import Collection
from uuid import UUID

from posthog.models import Team
from posthog.scopes.checks import scopes_not_covered

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.feature_flags.backend.facade.api import existing_flag_ids
from products.product_analytics.backend.facade.api import existing_insight_ids, insight_summaries
from products.surveys.backend.facade.api import existing_survey_ids, survey_summaries
from products.workflows.backend.facade.api import (
    get_recent_batch_jobs,
    get_workflow_summaries,
    get_workflow_view_access,
)
from products.workflows.backend.facade.contracts import WorkflowSummary

from ..facade import api, contracts

RECENT_SENDS_LIMIT = 20


class ReleaseLinkVisibility:
    """`held_scopes` are the API scopes of the viewer's key, or None for a request that scopes do not limit."""

    def __init__(self, *, team: Team, access_control: UserAccessControl, held_scopes: Collection[str] | None) -> None:
        self._team = team
        self._access_control = access_control
        self._held_scopes = held_scopes

    def _holds_scope(self, scope: str) -> bool:
        held = self._held_scopes
        return held is None or "*" in held or not scopes_not_covered(held, [scope])

    def flags(self, flag_ids: list[int]) -> contracts.FlagVisibility:
        team_id, access_control = self._team.id, self._access_control
        return contracts.FlagVisibility(
            existing=frozenset(existing_flag_ids(flag_ids, team_id=team_id, include_deleted=True)),
            visible=frozenset(
                existing_flag_ids(flag_ids, team_id=team_id, access_control=access_control, include_deleted=True)
            ),
            linkable=frozenset(existing_flag_ids(flag_ids, team_id=team_id, access_control=access_control)),
        )

    def can_read_workflows(self) -> bool:
        return self._holds_scope("hog_flow:read")

    def broadcasts(self, broadcast_ids: list[UUID]) -> contracts.BroadcastVisibility:
        requested = {str(broadcast_id): broadcast_id for broadcast_id in broadcast_ids}
        if not requested:
            return contracts.BroadcastVisibility(existing=frozenset(), visible=frozenset(), linkable=frozenset())
        if not self.can_read_workflows():
            return contracts.BroadcastVisibility(
                existing=frozenset(requested.values()), visible=frozenset(), linkable=frozenset()
            )
        team_id = self._team.id
        access = get_workflow_view_access(
            team_id=team_id, user_access_control=self._access_control, workflow_ids=requested.keys()
        )
        names = {
            summary.id: summary for summary in get_workflow_summaries(team_id=team_id, workflow_ids=requested.keys())
        }
        return contracts.BroadcastVisibility(
            existing=frozenset(requested.values()),
            visible=frozenset(broadcast_id for key, broadcast_id in requested.items() if access.allows(key)),
            linkable=frozenset(
                broadcast_id for key, broadcast_id in requested.items() if key in names and key in access.viewable_ids
            ),
            summaries=self._broadcast_summaries(
                {key: broadcast_id for key, broadcast_id in requested.items() if key in names and access.allows(key)},
                names,
            ),
        )

    def _broadcast_summaries(
        self, shown: dict[str, UUID], names: dict[str, WorkflowSummary]
    ) -> tuple[contracts.LinkedBroadcastDTO, ...]:
        sends = get_recent_batch_jobs(team_id=self._team.id, workflow_ids=shown.keys(), limit=RECENT_SENDS_LIMIT)
        return tuple(
            contracts.LinkedBroadcastDTO(
                id=broadcast_id,
                name=names[key].name,
                status=names[key].status,
                recent_sends=[
                    contracts.LinkedSendDTO(id=job.id, status=job.status, created_at=job.created_at)
                    for job in sends.get(key, [])
                ],
            )
            for key, broadcast_id in shown.items()
        )

    def surveys(self, survey_ids: list[UUID]) -> contracts.SurveyVisibility:
        team_id = self._team.id
        existing = frozenset(existing_survey_ids(survey_ids, team_id=team_id)) if survey_ids else frozenset()
        if not existing or not self._holds_scope("survey:read"):
            return contracts.SurveyVisibility(existing=existing, visible=frozenset(), linkable=frozenset())
        summaries = survey_summaries(survey_ids, team_id=team_id, access_control=self._access_control)
        visible = frozenset(summary.id for summary in summaries)
        return contracts.SurveyVisibility(
            existing=existing,
            visible=visible,
            linkable=visible,
            summaries=tuple(
                contracts.LinkedSurveyDTO(
                    id=summary.id,
                    name=summary.name,
                    created_at=summary.created_at,
                    start_date=summary.start_date,
                    end_date=summary.end_date,
                    linked_flag_id=summary.linked_flag_id,
                    archived=summary.archived,
                )
                for summary in summaries
            ),
        )

    def insights(self, insight_ids: list[int]) -> contracts.InsightVisibility:
        if not insight_ids:
            return contracts.InsightVisibility(existing=frozenset(), visible=frozenset(), linkable=frozenset())
        project_id = self._team.project_id
        existing = frozenset(existing_insight_ids(insight_ids, project_id=project_id, include_deleted=True))
        if not self._holds_scope("insight:read"):
            return contracts.InsightVisibility(existing=existing, visible=frozenset(), linkable=frozenset())
        summaries = insight_summaries(insight_ids, project_id=project_id, access_control=self._access_control)
        return contracts.InsightVisibility(
            existing=existing,
            visible=frozenset(summary.id for summary in summaries),
            linkable=frozenset(summary.id for summary in summaries if not summary.deleted),
            summaries=tuple(
                contracts.LinkedInsightDTO(
                    id=summary.id,
                    short_id=summary.short_id,
                    name=summary.name,
                    created_at=summary.created_at,
                    last_modified_at=summary.last_modified_at,
                    deleted=summary.deleted,
                )
                for summary in summaries
            ),
        )

    def lookups(self) -> api.LinkLookups:
        return api.LinkLookups(
            flags=self.flags, broadcasts=self.broadcasts, surveys=self.surveys, insights=self.insights
        )
