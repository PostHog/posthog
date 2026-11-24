"""Progress lines about a person-property sync or backfill that the run's owner can read in the UI.

The lines go to ``log_entries`` under ``log_source="warehouse_property_run"``, keyed by the warehouse
binding id. The sync module's own logger stays internal: it carries no ``log_source``, so none of its
lines can reach this source. Only this class names it, and it logs on a produce-only logger, so the
lines never also land in the worker's own log output.

Keep every line something a user can act on or understand. Put diagnostics on the module logger.
"""

from time import monotonic

from posthog.dataclasses import frozen
from posthog.temporal.common.logger import get_produce_only_logger

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import WarehouseBinding

# Pinned: the frontend log viewer and the runs table query log_entries by this value.
RUN_LOG_SOURCE = "warehouse_property_run"

# Progress lines repeat on a long run. This keeps a run to a few lines per minute whatever its batch size.
PROGRESS_INTERVAL_SECONDS = 30


@frozen
class RunEntities:
    """What a run updates, as the run's owner calls it."""

    singular: str
    plural: str


PEOPLE = RunEntities(singular="person", plural="people")
GROUPS = RunEntities(singular="group", plural="groups")
PEOPLE_AND_GROUPS = RunEntities(singular="person or group", plural="people and groups")


def run_entities(*, has_people: bool, has_groups: bool) -> RunEntities:
    if has_people and has_groups:
        return PEOPLE_AND_GROUPS
    return GROUPS if has_groups else PEOPLE


class PersonPropertyRunLog:
    def __init__(self, team_id: int, binding: WarehouseBinding, entities: RunEntities = PEOPLE) -> None:
        self._entities = entities
        self._last_progress_at: float | None = None
        self._saving_logged = False
        self._logger = get_produce_only_logger(__name__).bind(
            team_id=team_id, log_source=RUN_LOG_SOURCE, log_source_id=binding.id
        )

    def finding_latest_rows(self) -> None:
        self._logger.info(f"Finding the latest row for each {self._entities.singular}")

    def progress(self, *, rows_read: int, changed: int, existing: int, produced: int) -> None:
        """Cumulative counts for the run so far. Logged at most once per ``PROGRESS_INTERVAL_SECONDS``."""
        now = monotonic()
        if self._last_progress_at is not None and now - self._last_progress_at < PROGRESS_INTERVAL_SECONDS:
            return
        self._last_progress_at = now
        self._logger.info(f"Read {rows_read:,} {_count(rows_read, 'row', 'rows')}")
        if changed:
            matches = "matches" if existing == 1 else "match"
            self._logger.info(
                f"Checked {changed:,} changed {_count(changed, 'row', 'rows')}. "
                f"{existing:,} {matches} a {self._entities.singular}."
            )
        if produced:
            self._logger.info(f"Sent {produced:,} {_count(produced, 'update', 'updates')}")

    def saving_progress(self) -> None:
        """Logged once per run, however many sources it closes."""
        if not self._saving_logged:
            self._saving_logged = True
            self._logger.info("Saving progress")

    def finished(self, produced: int) -> None:
        entity = _count(produced, self._entities.singular, self._entities.plural)
        self._logger.info(f"Finished. Updated {produced:,} {entity}.")

    def failed(self, error: str) -> None:
        self._logger.error(error)


def _count(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural
