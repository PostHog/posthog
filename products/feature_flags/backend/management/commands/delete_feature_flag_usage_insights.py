from __future__ import annotations

import time
from dataclasses import dataclass, fields
from typing import Any
from uuid import UUID, uuid4

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils.timezone import now

from posthog.helpers.dashboard_templates import (
    FEATURE_FLAG_ENRICHED_INTERACTION_INSIGHT_NAME,
    FEATURE_FLAG_ENRICHED_VIEW_INSIGHT_NAME,
    FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME,
    FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_PREFIX,
    FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_SUFFIX,
)
from posthog.models.activity_logging.activity_log import Detail, LogActivityEntry, Trigger, bulk_log_activity
from posthog.models.file_system.constants import DEFAULT_SURFACE, surface_q
from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.utils import friendly_time

from products.alerts.backend.facade.api import insight_ids_with_alerts
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.facade.api import dashboard_ids_with_subscriptions, insight_ids_with_subscriptions
from products.feature_flags.backend.api.feature_flag import (
    USAGE_DASHBOARD_DESCRIPTION_PREFIX,
    USAGE_DASHBOARD_NAME_PREFIX,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.product_analytics.backend.facade.models import Insight

# Tags each activity-log entry so a sweep's deletions are distinguishable from a user's.
_JOB_TYPE = "delete_feature_flag_usage_insights"


def _classifier_q() -> Q:
    """Match only the insights auto-generated for feature flag usage dashboards.

    Keys on name and description, not on `is_sample`: every dashboard template sets that, so on its
    own it would also match billing/usage and onboarding insights. Callers wanting a second signal
    add it on top of this (see `_delete_orphaned`).
    Names come from constants in posthog/helpers/dashboard_templates.py, which is what creates them.
    Descriptions interpolate the flag key, so those are matched by fragment instead.
    """
    return (
        Q(name=FEATURE_FLAG_TOTAL_VOLUME_INSIGHT_NAME)
        | (
            Q(name__startswith=FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_PREFIX)
            & Q(name__endswith=FEATURE_FLAG_UNIQUE_CALLS_INSIGHT_NAME_SUFFIX)
        )
        | Q(name=FEATURE_FLAG_ENRICHED_VIEW_INSIGHT_NAME)
        | Q(name=FEATURE_FLAG_ENRICHED_INTERACTION_INSIGHT_NAME)
        | Q(description__startswith="Shows the number of", description__contains="calls made on feature flag")
        | Q(description__startswith="Shows the total number of times this feature was viewed")
    )


@dataclass(frozen=True, kw_only=True)
class _Candidate:
    """An insight considered for deletion, narrowed to the columns this sweep reads.

    Read as values rather than model instances: `select_related("team")` ignores `TeamManager`'s
    deferrals and would pull the fat taxonomy columns once per row, while `only()` turns
    `Insight.__init__`'s read of `query` into a refetch per row.
    """

    id: int
    short_id: str
    name: str | None
    derived_name: str | None
    favorited: bool
    is_sample: bool
    team_id: int
    organization_id: UUID


# Derived so a new `_Candidate` field can't drift from the columns fetched to populate it.
_CANDIDATE_FIELDS = tuple(f.name for f in fields(_Candidate))


def _candidate_rows(insights: QuerySet[Insight]) -> QuerySet[Insight, dict[str, Any]]:
    """Narrow an insight queryset to `_Candidate` values, keyed so each row splats into `_Candidate(**row)`."""
    return insights.annotate(organization_id=F("team__organization_id")).values(*_CANDIDATE_FIELDS)


@dataclass(frozen=True, kw_only=True)
class _SweepOptions:
    batch_size: int
    sleep_interval: float
    team_id: int | None
    limit: int | None
    dry_run: bool
    include_orphaned: bool
    keep_list_ids: frozenset[int]


@dataclass(frozen=False)
class _SweepStats:
    deleted: int = 0
    kept: int = 0
    flags_nulled: int = 0


class Command(BaseCommand):
    help = (
        "Soft-delete the insights PostHog auto-generates on feature flag usage dashboards, whether "
        "the owning flag is live or soft-deleted. Mirrors the insight bulk_delete side effects "
        "(tiles, activity log) and nulls FeatureFlag.usage_dashboard for any flag whose usage "
        "dashboard ends up empty."
    )

    options: _SweepOptions
    stats: _SweepStats
    run_id: str

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--batch-size", type=int, default=100, help="Flags (pass 1) or insights (pass 2) per batch")
        parser.add_argument("--sleep-interval", type=float, default=0.2, help="Sleep time between batches in seconds")
        parser.add_argument("--team-id", type=int, help="Restrict to a single team")
        parser.add_argument("--limit", type=int, help="Stop after soft-deleting this many insights (safety cap)")
        parser.add_argument(
            "--keep-ids-file",
            type=str,
            help=(
                "Path to a file of insight IDs to keep (one leading integer per line). "
                "Use this for the usage-based keep-list computed from the warehouse."
            ),
        )
        parser.add_argument(
            "--include-orphaned",
            action="store_true",
            help=(
                "Also sweep classified insights on generated dashboards that no flag row references, "
                "e.g. when a soft-deleted flag is hard-deleted to free its key for reuse. "
                "Off by default, so only insights a flag row (live or soft-deleted) still points at "
                "are removed. Scans the whole insight table, so run it off-peak."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without changing anything.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        self.options = _SweepOptions(
            batch_size=options["batch_size"],
            sleep_interval=options["sleep_interval"],
            team_id=options["team_id"],
            limit=options["limit"],
            dry_run=options["dry_run"],
            include_orphaned=options["include_orphaned"],
            keep_list_ids=self._load_keep_ids(options["keep_ids_file"]),
        )
        self.stats = _SweepStats()
        self.run_id = str(uuid4())

        if self.options.dry_run:
            self.stdout.write(self.style.WARNING("Running in dry-run mode - no changes will be made"))
        else:
            self.stdout.write(self.style.SUCCESS("Running in live mode - changes will be made to the database"))
        self.stdout.write(
            f"Configuration: batch_size={self.options.batch_size}, sleep_interval={self.options.sleep_interval}, "
            f"team_id={self.options.team_id}, limit={self.options.limit}, "
            f"include_orphaned={self.options.include_orphaned}, keep_list={len(self.options.keep_list_ids)}"
        )

        start_time = time.time()

        self._delete_referential()
        if self.options.include_orphaned:
            self._delete_orphaned()

        verb = "Would soft-delete" if self.options.dry_run else "Soft-deleted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {self.stats.deleted} insights, kept {self.stats.kept} (usage/keep-list), "
                f"nulled {self.stats.flags_nulled} flag usage_dashboard references "
                f"in {friendly_time(time.time() - start_time)}"
            )
        )

    def _load_keep_ids(self, path: str | None) -> frozenset[int]:
        if not path:
            return frozenset()
        keep_ids: set[int] = set()
        unparsed = 0
        try:
            # utf-8-sig so a BOM from a spreadsheet export doesn't eat the first id.
            with open(path, encoding="utf-8-sig") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    columns = [c.strip().strip('"') for c in stripped.split(",")]
                    if len(columns) > 1 and columns[0].isdecimal() and columns[1].isdecimal():
                        # Two leading numbers means the id is probably not the column being read, as in
                        # a team_id,insight_id export. Guessing here would protect the wrong insights.
                        raise CommandError(
                            f"--keep-ids-file {path} has more than one numeric column on a line: {stripped!r}. "
                            "Expected one insight ID per line, as the first comma-separated value."
                        )
                    # isdecimal, not isdigit: isdigit accepts characters like "²" that int() rejects.
                    if columns[0].isdecimal():
                        keep_ids.add(int(columns[0]))
                    else:
                        unparsed += 1
        except (OSError, UnicodeDecodeError) as e:
            raise CommandError(f"Could not read --keep-ids-file {path}: {e}")
        if unparsed and not keep_ids:
            # This file is the only thing protecting in-use insights, so a total parse failure has to
            # stop the run rather than silently sweep with no keep-list.
            raise CommandError(
                f"--keep-ids-file {path} yielded no insight IDs from {unparsed} non-blank lines. "
                "Expected one insight ID per line, as the first comma-separated value."
            )
        if unparsed:
            self.stdout.write(self.style.WARNING(f"Ignored {unparsed} unparsable lines in {path}"))
        return frozenset(keep_ids)

    @property
    def _limit_reached(self) -> bool:
        return self.options.limit is not None and self.stats.deleted >= self.options.limit

    def _throttle(self, *, wrote: bool) -> None:
        # A dry run issues only reads, so there is no write load to pace. Same for a batch that matched
        # nothing, which is the common case on a re-run: pacing it only slows the scan down.
        if self.options.dry_run or not wrote:
            return
        if self.options.sleep_interval > 0:
            time.sleep(self.options.sleep_interval)

    def _keep_ids(self, candidates: list[_Candidate]) -> set[int]:
        """Candidates to keep: edited, favorited, alerted, publicly shared, subscribed to, on a
        dashboard that is itself shared or subscribed to, or on the keep-list file.

        An insight without `is_sample` is one somebody edited. The generator sets that marker on every
        insight it creates, and `InsightSerializer.update` clears it on any PATCH, so its absence is
        the record that a user made this insight their own.

        The keep-list file carries the warehouse-derived usage signals. Postgres does record insight
        views in `InsightViewed`, but that is not usable as a keep signal here: the flag page embeds
        the usage dashboard, and loading a dashboard records a view for every tile on it, so opening
        a flag's Usage tab once marks all of its generated insights as viewed.
        """
        ids = [c.id for c in candidates]
        keep = {c.id for c in candidates if c.favorited or not c.is_sample or c.id in self.options.keep_list_ids}
        keep |= set(
            SharingConfiguration.objects.filter(insight_id__in=ids, enabled=True).values_list("insight_id", flat=True)
        )
        keep |= insight_ids_with_subscriptions(ids)
        keep |= insight_ids_with_alerts(ids)
        keep |= self._ids_on_dashboards_in_use(ids)
        return keep

    def _ids_on_dashboards_in_use(self, insight_ids: list[int]) -> set[int]:
        """Insights with a live tile on a dashboard that is itself shared or subscribed to.

        A dashboard-level share link or scheduled delivery serves every tile on the dashboard, so
        sweeping any of them would blank a surface someone still reads. The insight-level checks in
        `_keep_ids` cannot see these: a dashboard's SharingConfiguration and Subscription rows carry
        no insight id.
        """
        tiles = list(DashboardTile.objects.filter(insight_id__in=insight_ids).values_list("insight_id", "dashboard_id"))
        dashboard_ids = {dashboard_id for _, dashboard_id in tiles}
        if not dashboard_ids:
            return set()
        in_use = set(
            SharingConfiguration.objects.filter(dashboard_id__in=dashboard_ids, enabled=True).values_list(
                "dashboard_id", flat=True
            )
        )
        in_use |= dashboard_ids_with_subscriptions(dashboard_ids)
        return {insight_id for insight_id, dashboard_id in tiles if dashboard_id in in_use}

    def _deletable(self, candidates: list[_Candidate]) -> list[_Candidate]:
        """Candidates with no keep signal, truncated to what --limit still allows. Records the kept count."""
        keep = self._keep_ids(candidates)
        self.stats.kept += len(keep)
        deletable = [c for c in candidates if c.id not in keep]
        if self.options.limit is not None:
            deletable = deletable[: max(0, self.options.limit - self.stats.deleted)]
        return deletable

    def _soft_delete(self, insights: list[_Candidate]) -> None:
        """Mirror InsightViewSet.bulk_delete (products/product_analytics/backend/presentation/insight.py): soft-delete
        the insights and their tiles, then log each removal as system activity.

        Three of bulk_delete's steps are deliberately dropped: its alert teardown, because `_keep_ids`
        excludes alerted insights so none reach here; `last_modified_by`, because there is no acting
        user; and its `team__project_id` guard, which the candidate query already provides.
        """
        insight_ids = [i.id for i in insights]
        Insight.objects_including_soft_deleted.filter(id__in=insight_ids).update(deleted=True, last_modified_at=now())
        DashboardTile.objects_including_soft_deleted.filter(insight_id__in=insight_ids).update(deleted=True)
        self._prune_file_system_rows(insights)

        entries: list[LogActivityEntry] = []
        for insight in insights:
            name = insight.name or insight.derived_name
            if not name:
                continue
            entries.append(
                LogActivityEntry(
                    organization_id=insight.organization_id,
                    team_id=insight.team_id,
                    user=None,  # system-attributed (is_system=True)
                    was_impersonated=False,
                    item_id=insight.id,
                    scope="Insight",
                    activity="deleted",
                    detail=Detail(
                        name=name,
                        short_id=insight.short_id,
                        # Without this the customer's activity feed can't tell a maintenance sweep from
                        # someone on their own team deleting the insight.
                        trigger=Trigger(job_type=_JOB_TYPE, job_id=self.run_id, payload={}),
                    ),
                )
            )
        # A sweep must not put one CDP internal event per deleted insight onto the topic.
        bulk_log_activity(entries, notify=False)

    def _prune_file_system_rows(self, insights: list[_Candidate]) -> None:
        """Drop the project-tree rows for insights this sweep deleted.

        `FileSystemSyncMixin` prunes these on save, but the soft delete above goes through `.update()`,
        which fires no signal. Without this the swept insights stay listed under Unfiled/Insights and in
        Recents, and clicking one lands on "Insight not found".
        """
        tree_refs = Q()
        for insight in insights:
            tree_refs |= Q(team_id=insight.team_id, ref=insight.short_id)
        if not tree_refs:
            return
        surface = surface_q(DEFAULT_SURFACE)
        FileSystem.objects.filter(surface, tree_refs, type="insight").delete()
        FileSystemShortcut.objects.filter(surface, tree_refs, type="insight").delete()

    def _emptied_usage_dashboards(self, dashboard_ids: set[int], deleted_insight_ids: set[int]) -> set[int]:
        """Of these dashboards, the ones this delete leaves with no live tiles.

        Only dashboards that still had a tile going in can be emptied by us, so a dashboard that was
        already tile-less is left alone rather than counted as this run's work.
        """
        had_tiles: set[int] = set()
        keeps_a_tile: set[int] = set()
        for dashboard_id, insight_id in DashboardTile.objects.filter(dashboard_id__in=dashboard_ids).values_list(
            "dashboard_id", "insight_id"
        ):
            had_tiles.add(dashboard_id)
            if insight_id not in deleted_insight_ids:
                keeps_a_tile.add(dashboard_id)
        return had_tiles - keeps_a_tile

    def _unlink_usage_dashboards(self, emptied: set[int]) -> None:
        """Null usage_dashboard on every flag pointing at one of these dashboards, soft-deleted flags
        included: FeatureFlagViewSet.dashboard regenerates only when the FK is null or its dashboard
        row is deleted, and this sweep leaves the dashboard alive, so a flag restored while still
        linked would reopen its emptied dashboard instead.

        Reports the pairs it severs: unlike the soft deletes, this write keeps no copy of the old
        value, so its own output is what makes the run reversible.
        """
        # Read the pairs once and write against those ids, so the lines an operator would replay from
        # are the rows actually written.
        severed = list(
            FeatureFlag.objects_including_soft_deleted.filter(usage_dashboard_id__in=emptied).values_list(
                "id", "usage_dashboard_id"
            )
        )
        for flag_id, dashboard_id in severed:
            self.stdout.write(f"  unlink flag_id={flag_id} usage_dashboard_id={dashboard_id}")
        if not self.options.dry_run:
            FeatureFlag.objects_including_soft_deleted.filter(id__in=[flag_id for flag_id, _ in severed]).update(
                usage_dashboard=None
            )
        self.stats.flags_nulled += len(severed)

    def _usage_dashboard_flags(self) -> QuerySet[FeatureFlag]:
        """Every flag row that vouches for a usage dashboard, soft-deleted rows included: deleting
        a flag never touches usage_dashboard, so the row still proves PostHog generated whatever
        the dashboard holds. Pass 1 scans it and pass 2 excludes it, so both passes must read flags
        through this one queryset.
        """
        flags = FeatureFlag.objects_including_soft_deleted.filter(usage_dashboard_id__isnull=False)
        if self.options.team_id is not None:
            flags = flags.filter(team_id=self.options.team_id)
        return flags

    def _delete_referential(self) -> None:
        """Pass 1: the authoritative set, meaning insights on any FeatureFlag.usage_dashboard that
        match the classifier."""
        flag_rows = self._usage_dashboard_flags().order_by("id").values_list("id", "usage_dashboard_id")

        self.stdout.write("Pass 1 (referential): scanning feature flags with a usage dashboard")
        last_id = 0
        while not self._limit_reached:
            flag_batch = list(flag_rows.filter(id__gt=last_id)[: self.options.batch_size])
            if not flag_batch:
                break
            last_id = flag_batch[-1][0]
            dashboard_ids = {dash_id for _, dash_id in flag_batch}

            # Live tiles (default manager excludes deleted tiles and deleted dashboards) on these dashboards.
            live_tiles = DashboardTile.objects.filter(dashboard_id__in=dashboard_ids, insight__isnull=False)
            classified = Insight.objects.filter(_classifier_q(), id__in=live_tiles.values("insight_id"))
            if self.options.team_id is not None:
                classified = classified.filter(team_id=self.options.team_id)
            classified = classified.order_by("id")
            deletable = self._deletable([_Candidate(**row) for row in _candidate_rows(classified)])

            emptied = self._emptied_usage_dashboards(dashboard_ids, {c.id for c in deletable})
            if self.options.dry_run:
                if emptied:
                    self._unlink_usage_dashboards(emptied)
            else:
                with transaction.atomic():
                    if deletable:
                        self._soft_delete(deletable)
                    if emptied:
                        self._unlink_usage_dashboards(emptied)
            self.stats.deleted += len(deletable)

            self.stdout.write(
                f"Pass 1: through flag id {last_id} | deleted {self.stats.deleted} | kept {self.stats.kept} | "
                f"flags nulled {self.stats.flags_nulled}"
            )
            self._throttle(wrote=bool(deletable or emptied))

    def _delete_orphaned(self) -> None:
        """Pass 2 (opt-in): generated insights left on a generated dashboard no flag row points at."""
        # Anchor on the dashboard the generator stamps, so a name match is never the only evidence that
        # PostHog created the insight. Pass 1 owns every dashboard a flag row still references, so this
        # pass exists for dashboards with no flag row at all (hard-deleted rows, see
        # _free_key_held_by_soft_deleted_flags in products/feature_flags/backend/api/feature_flag.py);
        # ones whose dashboard was deleted outright stay out of scope.
        generated_dashboards = Dashboard.objects.filter(
            creation_mode="template",
            name__startswith=USAGE_DASHBOARD_NAME_PREFIX,
            description__startswith=USAGE_DASHBOARD_DESCRIPTION_PREFIX,
        )
        # Requiring the generator's marker keeps rows an edit has already disqualified out of the scan
        # entirely. `_keep_ids` would spare them anyway, so this only saves fetching them.
        insights = Insight.objects.filter(
            _classifier_q(),
            is_sample=True,
            id__in=DashboardTile.objects.filter(dashboard_id__in=generated_dashboards.values("id")).values(
                "insight_id"
            ),
        )
        if self.options.team_id is not None:
            insights = insights.filter(team_id=self.options.team_id)
        insight_rows = _candidate_rows(insights.order_by("id"))

        self.stdout.write("Pass 2 (orphaned): scanning generated dashboards no flag row points at")
        last_id = 0
        while not self._limit_reached:
            batch = [_Candidate(**row) for row in insight_rows.filter(id__gt=last_id)[: self.options.batch_size]]
            if not batch:
                break
            last_id = batch[-1].id

            # Drop any still reachable from a flag's usage dashboard, since pass 1 owns those.
            reachable = set(
                DashboardTile.objects.filter(
                    insight_id__in=[c.id for c in batch],
                    dashboard_id__in=self._usage_dashboard_flags().values("usage_dashboard_id"),
                ).values_list("insight_id", flat=True)
            )
            deletable = self._deletable([c for c in batch if c.id not in reachable])

            if deletable and not self.options.dry_run:
                with transaction.atomic():
                    self._soft_delete(deletable)
            self.stats.deleted += len(deletable)

            self.stdout.write(
                f"Pass 2: through insight id {last_id} | deleted {self.stats.deleted} | kept {self.stats.kept}"
            )
            self._throttle(wrote=bool(deletable))
