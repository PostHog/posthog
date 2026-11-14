"""Who authors a report through the report channel.

`emit_report` and `edit_report` read every author-specific value through `ReportAuthor`: the
idempotency scope, the telemetry identity, the preflight gates, and the artefact attribution. Two
authors exist: a scout run (`ScoutRunReportAuthor`) and a project member who files a report through the
report API, usually over the MCP (`UserReportAuthor`). Both implement the same protocol, so neither path
forks on who wrote the report.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.daily_limit import team_day_start
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalScoutRun
from products.signals.backend.scout_harness.tools.emit import (
    _assert_team_owns_run,
    _preflight_emit_gates,
    _resolve_task_id,
)


class ReportAuthor(Protocol):
    @property
    def scout_run(self) -> SignalScoutRun | None:
        """The run behind the report. It feeds the run's report and edit tallies, the provenance note,
        the `task_run` artefact, the scout's configured Slack destination, private trial capture, and
        the in-progress check that an edit runs under the run's lock. None when no scout run authors
        the report, which skips all of them."""
        ...

    @property
    def skill_name(self) -> str | None:
        """The skill whose owners get reviewer provenance stamps. None stamps no one."""
        ...

    @property
    def user_id(self) -> int | None:
        """The project member who filed the report by hand, or None for a scout. A set value stores the
        report as `user_authored`, which keeps automatic start off, and skips the repository selection
        sandbox."""
        ...

    @property
    def can_edit_reports(self) -> bool:
        """Whether the author can call `edit_report`. Quality hints name `edit_report` only for an author
        that can call it."""
        ...

    @property
    def idempotency_scope(self) -> str:
        """The prefix of the stored emit key. A retry resolves to the first report only inside one
        scope, so two authors never replay each other's reports."""
        ...

    @property
    def distinct_id(self) -> str:
        """The distinct id of the customer-facing copy of the report events."""
        ...

    def event_properties(self) -> dict[str, Any]: ...

    def log_extra(self) -> dict[str, Any]: ...

    def assert_owned_by(self, team: Team) -> None: ...

    def preflight_skip_reason(self, team: Team) -> str | None:
        """The `skipped_reason` of the first gate that drops the emit, or None. Reads the DB, so call
        it on a sync thread."""
        ...

    def attribution(self) -> ArtefactAttribution:
        """Who the report's artefacts are attributed to. Reads the DB, so call it on a sync thread."""
        ...


@frozen
class ScoutRunReportAuthor:
    run: SignalScoutRun

    @property
    def scout_run(self) -> SignalScoutRun | None:
        return self.run

    @property
    def skill_name(self) -> str | None:
        return self.run.skill_name

    @property
    def user_id(self) -> int | None:
        return None

    @property
    def can_edit_reports(self) -> bool:
        # The stamp, not the skill, because the run's prompt was built from the stamped tool list. An
        # unstamped run counts as unable to edit, so no hint sends it to an endpoint that can refuse it.
        return (self.run.metadata or {}).get("report_channel") in ("edit", "both")

    @property
    def idempotency_scope(self) -> str:
        # Stored keys and event uuids hash this value. Changing its format lets a retry that crosses
        # a deploy author a second report and fire a second customer-facing event.
        return str(self.run.id)

    @property
    def distinct_id(self) -> str:
        return f"signals_scout:{self.run.skill_name}"

    def event_properties(self) -> dict[str, Any]:
        """Shared dimensions for the report-channel lifecycle events, mirroring the `signals_scout_run_*`
        events so the two join on `run_id` / `task_run_id` — a report event sits under the run that authored
        it. All fields are plain columns on the bridge row (no FK query)."""
        metadata = self.run.metadata or {}
        return {
            **{
                key: metadata[key]
                for key in (
                    "experiment_key",
                    "experiment_variant",
                    "$feature/self-driving-banger-scout",
                    "runtime",
                    "model",
                    "service_tier",
                )
                if key in metadata
            },
            "skill_name": self.run.skill_name,
            "skill_version": self.run.skill_version,
            "scout_config_id": str(self.run.scout_config_id) if self.run.scout_config_id else None,
            "run_id": str(self.run.id),
            "task_run_id": str(self.run.task_run_id) if self.run.task_run_id else None,
        }

    def log_extra(self) -> dict[str, Any]:
        return {"run_id": str(self.run.id), "skill_name": self.run.skill_name}

    def assert_owned_by(self, team: Team) -> None:
        _assert_team_owns_run(team, self.run)

    def preflight_skip_reason(self, team: Team) -> str | None:
        return _preflight_emit_gates(team, self.run)

    def attribution(self) -> ArtefactAttribution:
        task_id = _resolve_task_id(self.run)
        return ArtefactAttribution.from_task(task_id) if task_id is not None else ArtefactAttribution.system()


USER_REPORT_DAILY_LIMIT = 20
USER_REPORT_DAILY_LIMIT_REASON = "user_daily_report_limit"
AI_PROCESSING_NOT_APPROVED_REASON = "ai_processing_not_approved"


def user_reports_created_today(team: Team, user_id: int) -> int:
    """Reports this member filed by hand since the start of the project's day. Suppressed and deleted
    reports count too, because each one already paid for a safety judge call."""
    return SignalReport.objects.filter(
        team_id=team.id, created_by_id=user_id, user_authored=True, created_at__gte=team_day_start(team)
    ).count()


def user_report_limit_resets_at(team: Team) -> datetime:
    return team_day_start(team) + timedelta(days=1)


@frozen
class UserReportAuthor:
    """A project member who files a report through `POST /signals/reports/`.

    The scout source toggle and scout configs do not apply: they control scouts, not a person.
    Ownership needs no check, because the viewset already scopes the request to the team."""

    user_id: int
    user_distinct_id: str
    request_attribution: ArtefactAttribution
    client_name: str | None = None

    @property
    def scout_run(self) -> SignalScoutRun | None:
        return None

    @property
    def skill_name(self) -> str | None:
        return None

    @property
    def can_edit_reports(self) -> bool:
        return False

    @property
    def idempotency_scope(self) -> str:
        # Stored keys and event uuids hash this value, so changing its format breaks retries across a deploy.
        return f"user:{self.user_id}"

    @property
    def distinct_id(self) -> str:
        return self.user_distinct_id

    def event_properties(self) -> dict[str, Any]:
        properties: dict[str, Any] = {"author_type": "user"}
        if self.client_name:
            properties["mcp_client_name"] = self.client_name
        return properties

    def log_extra(self) -> dict[str, Any]:
        return {"author_type": "user", "user_id": self.user_id}

    def assert_owned_by(self, team: Team) -> None:
        return None

    def preflight_skip_reason(self, team: Team) -> str | None:
        if not team.organization.is_ai_data_processing_approved:
            return AI_PROCESSING_NOT_APPROVED_REASON
        if user_reports_created_today(team, self.user_id) >= USER_REPORT_DAILY_LIMIT:
            return USER_REPORT_DAILY_LIMIT_REASON
        return None

    def attribution(self) -> ArtefactAttribution:
        return self.request_attribution
