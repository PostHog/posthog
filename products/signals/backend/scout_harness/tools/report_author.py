"""Who authors a report through the report channel.

`emit_report` and `edit_report` read every author-specific value through `ReportAuthor`: the
idempotency scope, the telemetry identity, the preflight gates, and the artefact attribution. A scout
run is the only author that exists. Another author, such as a user who calls the channel over the MCP,
implements the same protocol, so neither path forks on who wrote the report.
"""

from __future__ import annotations

from typing import Any, Protocol

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.models import ArtefactAttribution, SignalScoutRun
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
        return {
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
