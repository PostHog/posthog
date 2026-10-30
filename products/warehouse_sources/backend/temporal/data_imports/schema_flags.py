"""Rollout flags for the import pipeline, per schema or per team.

A leaf module (no deltalake/pyarrow, no pipeline imports) so an activity can gate on a flag
without pulling the Delta stack into its import graph.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from django.db import InterfaceError, OperationalError

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.utils import retry_on_db_connection_drop

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def is_schema_flag_enabled(schema: ExternalDataSchema, flag: str) -> bool:
    """Evaluate a rollout flag for this schema.

    `schema_id`, `team_id`, and `source_type` are passed as person properties so the flag can be
    released to a single table — set a release condition `schema_id = <id>` to dogfood a feature
    on one schema before rolling out by team/org/project.
    """
    return _is_flag_enabled_for_team(
        schema.team_id,
        flag,
        lambda: {
            "schema_id": str(schema.id),
            "team_id": str(schema.team_id),
            "source_type": schema.source.source_type,
        },
    )


def is_team_flag_enabled(team_id: int, flag: str, *, raise_on_error: bool = False) -> bool:
    """Evaluate a rollout flag for a whole team, released by team, project or organization.

    By default never raises: an evaluation failure means the flag is off. With ``raise_on_error``, a
    failure is still captured but then re-raised, so a caller that caches the result can tell a failed
    evaluation from a flag that is off.
    """
    return _is_flag_enabled_for_team(team_id, flag, lambda: {"team_id": str(team_id)}, raise_on_error=raise_on_error)


def _is_flag_enabled_for_team(
    team_id: int,
    flag: str,
    person_properties: Callable[[], dict[str, str]],
    *,
    raise_on_error: bool = False,
) -> bool:
    from posthog.models import Team  # noqa: PLC0415 — keeps this module importable before app registry setup

    try:
        team = retry_on_db_connection_drop(lambda: Team.objects.only("uuid", "organization_id").get(id=team_id))
    except Team.DoesNotExist:
        return False
    except (OperationalError, InterfaceError) as e:
        # retry_on_db_connection_drop already retried once; a second failure is a genuinely degraded
        # DB, not a bug here. Some callers (repartition_table.py) evaluate this flag with no enclosing
        # try/except, so this function's contract of "never raises, defaults to disabled" must hold on
        # its own.
        capture_exception(e)
        if raise_on_error:
            raise
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                person_properties=person_properties(),
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        if raise_on_error:
            raise
        return False
