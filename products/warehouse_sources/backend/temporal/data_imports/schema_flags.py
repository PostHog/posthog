"""Per-schema rollout flags for the import pipeline.

A leaf module (no deltalake/pyarrow, no pipeline imports) so an activity can gate on a flag
without pulling the Delta stack into its import graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import InterfaceError, OperationalError

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.utils import retry_on_db_connection_drop

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

# Rollout for completing a run on a negative source probe (see `_fast_return_eligible`).
WAREHOUSE_FAST_RETURN_FLAG = "data-warehouse-fast-return"


def is_fast_return_enabled(schema: ExternalDataSchema) -> bool:
    return is_schema_flag_enabled(schema, WAREHOUSE_FAST_RETURN_FLAG)


def is_schema_flag_enabled(schema: ExternalDataSchema, flag: str) -> bool:
    """Evaluate a rollout flag for this schema.

    `schema_id`, `team_id`, and `source_type` are passed as person properties so the flag can be
    released to a single table — set a release condition `schema_id = <id>` to dogfood a feature
    on one schema before rolling out by team/org/project.
    """
    from posthog.models import Team  # noqa: PLC0415 — keeps this module importable before app registry setup

    try:
        team = retry_on_db_connection_drop(lambda: Team.objects.only("uuid", "organization_id").get(id=schema.team_id))
    except Team.DoesNotExist:
        return False
    except (OperationalError, InterfaceError) as e:
        # retry_on_db_connection_drop already retried once; a second failure is a genuinely degraded
        # DB, not a bug here. Some callers (repartition_table.py) evaluate this flag with no enclosing
        # try/except, so this function's contract of "never raises, defaults to disabled" must hold on
        # its own.
        capture_exception(e)
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                person_properties={
                    "schema_id": str(schema.id),
                    "team_id": str(schema.team_id),
                    "source_type": schema.source.source_type,
                },
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
        return False
