"""The anomaly taxonomy for a duckgres usage pull — one table, one policy bit.

Every way a pull can be wrong is detected here, as data. Each anomaly carries a
single policy bit, `recoverable`:

- **recoverable=True** — a re-pull can still capture the data we missed, so the
  caller WITHHOLDS the ack: acking would let duckgres delete source buckets this
  pull didn't fully capture, turning a transient problem into permanent
  under-billing.
- **recoverable=False** — re-pulling cannot change the outcome (an orphan org,
  a broken org id, an impossible value), so the caller alerts and the ack
  PROCEEDS. Depending on the anomaly, evidence is retained or the invalid row
  is dropped.

`should_ack` is derived, not hand-assembled: no recoverable anomaly → ack. To
add anomaly #12, add one detection block here — the ack decision, the alert,
and the log follow from the table.

Detection is pure (no I/O): the activity computes its inputs and passes them in,
so the whole withhold/proceed matrix is unit-testable without a database.
"""

import datetime as dt
import dataclasses

from products.managed_warehouse.backend.temporal.duckgres_usage.client import UsageResponse
from products.managed_warehouse.backend.temporal.duckgres_usage.team_resolution import ResolvedTeams


class DuckgresWatermarkHole(Exception):
    """Duckgres's cursor is ahead of our last recorded ack — it deleted buckets
    past what we have any record of processing, so billable usage may be lost."""


class DuckgresRowParseError(Exception):
    """One or more duckgres usage rows could not be parsed and were dropped."""


class DuckgresRowsOutsideWindow(Exception):
    """Duckgres served rows dated outside the ack window (at or below its own
    cursor). They were dropped, not persisted, so the ack is withheld — acking
    could delete their source buckets and permanently under-bill."""


class DuckgresUsageOrphanedOrg(Exception):
    """An org's managed-warehouse usage had no billable team to attribute it to.
    The row remains in the mirror but is omitted from usage reports until a
    replacement exists. The ack proceeds because re-pulling cannot repair team
    state."""


class DuckgresMalformedOrgRows(Exception):
    """Duckgres served usage rows whose org_id is not a PostHog org UUID — a broken
    contract (the dev seed's org named 'local' is a live example). The rows are
    dropped and the ack DELIBERATELY proceeds: a bucket's org_id never changes, so
    withholding would freeze the ack forever on permanently-bad data. Loud so the
    upstream contract break gets fixed; never loop-breaking."""


class DuckgresDuplicateRows(Exception):
    """Duckgres emitted the same billing key more than once with an *identical* row (a
    contract violation — its API serves one row per key per day). Harmless: we kept one
    of each and dropped the rest, and the ack still proceeds. The dup itself is a bug."""


class DuckgresConflictingRows(Exception):
    """Duckgres emitted the same billing key with *different* measures — a partial and a
    corrected total, say. We can't tell which is right, so we keep the larger and withhold
    the ack, leaving duckgres to hold the source for reconciliation instead of deleting it."""


class DuckgresForeignTeamRows(Exception):
    """Duckgres stamped a usage row for one org with a live team that belongs to a
    *different* org — a duckgres/provisioning bug (it should stamp the org's own team).
    The rows are dropped and the ack proceeds: the org, not the stamped team, is the
    billing authority, so we never charge the wrong org, and a mis-stamped bucket won't
    fix itself on a re-pull. Loud so the upstream bug gets found; never loop-breaking."""


class DuckgresInvalidValueRows(Exception):
    """Duckgres served rows carrying an impossible measure — NaN, infinity, or a
    negative amount. They were dropped so they can't corrupt the mirror, and the ack
    DELIBERATELY proceeds: an impossible value never becomes valid on a re-pull, so
    withholding would freeze the ack forever. Loud so the upstream computation bug is
    found; the worst case is a best-effort under-bill we can correct later."""


class DuckgresMissingUsage(Exception):
    """The usage response carried no usage array at all (the key was absent or not a
    list), which we cannot read as "the window truly had no usage". We persisted
    nothing (an empty family never wipes the mirror) and WITHHOLD the ack so duckgres
    keeps the source buckets until a well-formed response lands."""


class DuckgresMalformedStorage(Exception):
    """The storage collection was absent or not a list, so we cannot read it as
    "no storage". We persisted nothing for storage and WITHHOLD the ack, since the
    shared ack would otherwise delete storage buckets we never captured."""


class DuckgresUsageRegression(Exception):
    """A newer snapshot decreased or omitted an org's previously mirrored
    product/day total. The org retained its last-good snapshot and the shared ack
    was withheld so the source remains available for reconciliation."""


@dataclasses.dataclass(frozen=True)
class Anomaly:
    kind: str
    # True → a re-pull can recover what this pull missed → the ack is withheld.
    # False → permanently bad data was dropped → alert, but the ack proceeds.
    recoverable: bool
    exception: type[Exception]
    message: str
    # None means the anomaly cannot be safely scoped and blocks promotion for
    # every org. A set quarantines only those orgs while healthy orgs advance.
    organization_ids: frozenset[str] | None = None

    def to_exception(self) -> Exception:
        return self.exception(self.message)


def detect_anomalies(
    response: UsageResponse,
    resolution: ResolvedTeams,
    recorded: dt.datetime | None,
    out_of_window: int,
) -> list[Anomaly]:
    """Everything wrong with this pull, each with its withhold/proceed policy."""
    found: list[Anomaly] = []

    if recorded is not None and response.watermark_low > recorded:
        found.append(
            Anomaly(
                "watermark_hole",
                recoverable=True,
                exception=DuckgresWatermarkHole,
                message=(
                    f"duckgres watermark_low {response.watermark_low.isoformat()} is ahead of last acked "
                    f"{recorded.isoformat()}; persisted this window but withheld the ack"
                ),
            )
        )
    if response.unparsed_row_count:
        found.append(
            Anomaly(
                "parse_failure",
                recoverable=True,
                exception=DuckgresRowParseError,
                message=(
                    f"dropped {response.unparsed_row_count} unparseable duckgres usage row(s) and withheld "
                    f"the ack; sample: {response.unparsed_row_sample}"
                ),
            )
        )
    if out_of_window:
        found.append(
            Anomaly(
                "out_of_window",
                recoverable=True,
                exception=DuckgresRowsOutsideWindow,
                message=(
                    f"dropped {out_of_window} duckgres row(s) dated outside the ack window "
                    f"(watermark_low {response.watermark_low.isoformat()}) and withheld the ack"
                ),
            )
        )
    if resolution.orphaned_org_ids:
        found.append(
            Anomaly(
                "orphaned_org",
                recoverable=False,
                exception=DuckgresUsageOrphanedOrg,
                message=(
                    f"managed-warehouse usage for {len(resolution.orphaned_org_ids)} orphan org(s) with no "
                    f"billable team to attribute it to (rows retained but omitted from reports; ack proceeds): "
                    f"{sorted(resolution.orphaned_org_ids)}"
                ),
            )
        )
    if resolution.malformed_org_row_count:
        found.append(
            Anomaly(
                "malformed_org",
                recoverable=False,
                exception=DuckgresMalformedOrgRows,
                message=(
                    f"dropped {resolution.malformed_org_row_count} duckgres usage row(s) with a non-UUID "
                    f"org_id (sample: {list(resolution.malformed_org_id_sample)}); ack proceeds — "
                    "a bucket's org_id never changes, so these can never become billable"
                ),
            )
        )
    if resolution.foreign_team_row_count:
        found.append(
            Anomaly(
                "foreign_team",
                recoverable=False,
                exception=DuckgresForeignTeamRows,
                message=(
                    f"dropped {resolution.foreign_team_row_count} duckgres usage row(s) whose live team "
                    f"belongs to a different org (sample team ids: {list(resolution.foreign_team_sample)}); "
                    "ack proceeds — the org is the billing authority, so we never charge the wrong org"
                ),
            )
        )
    if resolution.duplicate_row_count:
        found.append(
            Anomaly(
                "duplicate_rows",
                recoverable=False,
                exception=DuckgresDuplicateRows,
                message=(
                    f"duckgres emitted {resolution.duplicate_row_count} exact-duplicate usage row(s) for the "
                    "same billing key; kept one of each and dropped the rest"
                ),
            )
        )
    if resolution.conflicting_row_count:
        found.append(
            Anomaly(
                "conflicting_rows",
                recoverable=True,
                exception=DuckgresConflictingRows,
                message=(
                    f"duckgres emitted {resolution.conflicting_row_count} usage row(s) sharing a billing key "
                    "but with different measures; retained each affected org's last-good mirror and withheld "
                    "the ack for reconciliation"
                ),
                organization_ids=frozenset(resolution.conflicting_org_ids),
            )
        )
    if response.invalid_value_row_count:
        found.append(
            Anomaly(
                "invalid_value",
                recoverable=False,
                exception=DuckgresInvalidValueRows,
                message=(
                    f"dropped {response.invalid_value_row_count} duckgres usage row(s) with an impossible "
                    f"measure (NaN, infinity, or negative); sample: {response.invalid_value_row_sample}; "
                    "ack proceeds — an impossible value can never become valid on a re-pull"
                ),
            )
        )
    if response.usage_missing:
        found.append(
            Anomaly(
                "usage_missing",
                recoverable=True,
                exception=DuckgresMissingUsage,
                message=(
                    "duckgres usage response carried no usage array (key absent or not a list); persisted "
                    "nothing and withheld the ack until a well-formed response lands"
                ),
            )
        )
    if response.storage_malformed:
        found.append(
            Anomaly(
                "storage_malformed",
                recoverable=True,
                exception=DuckgresMalformedStorage,
                message=(
                    "duckgres usage response carried no storage list (key absent or not a list); persisted no "
                    "storage and withheld the ack until a well-formed response lands"
                ),
            )
        )
    return found


def regression_anomaly(organization_ids: set[str]) -> Anomaly:
    return Anomaly(
        "usage_regression",
        recoverable=True,
        exception=DuckgresUsageRegression,
        message=(
            f"a newer duckgres snapshot decreased or omitted usage for {len(organization_ids)} org(s); "
            f"retained their last-good mirror rows and withheld the ack: {sorted(organization_ids)}"
        ),
        organization_ids=frozenset(organization_ids),
    )
