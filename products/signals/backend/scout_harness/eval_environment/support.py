from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid5

from products.signals.backend.scout_harness.eval_environment.schema import ScoutEnvironmentCase


class ScoutEnvironmentSupport:
    CONFIG_FIELDS = frozenset(
        {
            "display_name",
            "emit",
            "model",
            "allowed_mcp_tools",
            "tool_preset",
            "write_scopes",
            "structured_output_schema",
            "tags",
            "run_interval_minutes",
            "run_cron_schedule",
            "precheck_query",
            "precheck_disabled",
            "rubrics",
            "lifecycle_locked",
            "network_access",
            "created_at",
            "updated_at",
            "last_run_at",
            "enabled",
            "mcp_gateway_server_ids",
            "output_destinations",
            "repositories",
        }
    )
    REPORT_FIELDS = frozenset(
        {
            "status",
            "status_before_suppression",
            "total_weight",
            "signal_count",
            "signals_at_run",
            "run_count",
            "signals_researched",
            "implemented_at_run_count",
            "content_revision_count",
            "implemented_at_revision_count",
            "corroboration_count",
            "title",
            "summary",
            "error",
            "charts",
            "metrics",
            "suggested_prompts",
            "promoted_at",
            "last_run_at",
            "monitoring_started_at",
            "first_visible_at",
            "inbox_notified_at",
            "latest_actionability",
            "latest_already_addressed",
            "billing_exempt_reason",
        }
    )
    RUN_FIELDS = frozenset(
        {
            "skill_name",
            "skill_version",
            "summary",
            "emitted_count",
            "emitted_finding_ids",
            "emitted_report_ids",
            "edited_report_ids",
            "metadata",
            "total_spend",
        }
    )
    RUN_CONTEXT_FIELDS = frozenset(
        {"task_id", "task_run_id", "status", "started_at", "completed_at", "error", "failure_reason", "task_url"}
    )
    PROFILE_FIELDS = frozenset({"expires_at", "source_version", "payload"})
    NOTE_FIELDS = frozenset({"skill_name", "content", "created_by_id", "expires_at", "origin"})
    MEMORY_FIELDS = frozenset({"key", "content", "created_by_run_id", "created_by_identity", "expires_at"})
    ARTEFACT_FIELDS = frozenset(
        {"report_id", "type", "content", "actor_kind", "actor_agent", "created_by_id", "task_id", "claim_id"}
    )
    DATE_FIELDS = frozenset(
        {
            "created_at",
            "updated_at",
            "last_run_at",
            "promoted_at",
            "monitoring_started_at",
            "first_visible_at",
            "inbox_notified_at",
            "started_at",
            "completed_at",
            "expires_at",
        }
    )

    @staticmethod
    def validate_connections(config: Mapping[str, object]) -> None:
        if any(config.get(name) for name in ("mcp_gateway_server_ids", "repositories")):
            raise ValueError("External scout connections are not supported by portable environments.")
        destinations = config.get("output_destinations", {})
        if not isinstance(destinations, dict) or set(destinations) - {"slack", "webhook", "inbox"}:
            raise ValueError("The scout output destinations are unsupported by portable environments.")
        if any(destinations.get(name) not in (None, {}) for name in ("slack", "webhook")):
            raise ValueError("External scout destinations are not supported by portable environments.")
        if "inbox" in destinations and not isinstance(destinations["inbox"], bool):
            raise ValueError("The local inbox destination must be a boolean.")

    @classmethod
    def _validate_dates(cls, fields: Mapping[str, object], case: ScoutEnvironmentCase) -> None:
        for name in cls.DATE_FIELDS & fields.keys():
            if fields[name] is None:
                continue
            value = fields[name]
            if not isinstance(value, str):
                raise ValueError("Scout state dates must be timezone-aware ISO strings.")
            try:
                timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Scout state dates must be valid ISO strings.") from None
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Scout state dates must include a timezone.")
            if name != "expires_at" and timestamp > case.checkpoint:
                raise ValueError("Scout state dates cannot be after the bundle checkpoint.")

    @classmethod
    def validate(cls, case: ScoutEnvironmentCase) -> None:
        if set(case.config) - (cls.CONFIG_FIELDS | {"reasoning_effort"}):
            raise ValueError("The scout configuration contains unsupported restore fields.")
        cls.validate_connections(case.config)
        if case.config.get("structured_output_schema"):
            raise ValueError("Scout trials do not support this scout's structured output.")
        users = {source.id for source in case.users} | {str(source.uuid) for source in case.users if source.uuid}
        runs = {record.id for record in case.state.runs}
        reports = {record.id for record in case.state.reports}
        tasks = {UUID(str(record.fields.get("task_id") or uuid5(record.id, "task"))) for record in case.state.runs}
        groups = (
            (case.state.runs, cls.RUN_FIELDS | cls.RUN_CONTEXT_FIELDS),
            (case.state.reports, cls.REPORT_FIELDS),
            (case.state.report_artefacts, cls.ARTEFACT_FIELDS),
            (case.state.notes, cls.NOTE_FIELDS),
            (case.state.memory, cls.MEMORY_FIELDS),
            ([case.state.profile] if case.state.profile else [], cls.PROFILE_FIELDS),
        )
        for records, allowed in groups:
            for record in records:
                if set(record.fields) - allowed:
                    raise ValueError("The scout starting state contains unsupported restore fields.")
                for name, value in record.fields.items():
                    if value is None:
                        continue
                    if name == "created_by_id" and str(value) not in users:
                        raise ValueError("Starting-state user references must resolve inside the bundle.")
                    if name == "created_by_run_id" and UUID(str(value)) not in runs:
                        raise ValueError("Starting-state memory requires its source run in the bundle.")
                    if name == "report_id" and UUID(str(value)) not in reports:
                        raise ValueError("Starting-state artefacts require their report in the bundle.")
                    if name == "task_id" and UUID(str(value)) not in tasks:
                        raise ValueError("Starting-state task references must resolve inside the bundle.")
                    if name == "claim_id":
                        raise ValueError("Scout artefact claim references are not supported by portable environments.")
                    if name in {"task_id", "task_run_id"}:
                        UUID(str(value))
                cls._validate_dates(record.fields, case)
        cls._validate_dates(case.config, case)
