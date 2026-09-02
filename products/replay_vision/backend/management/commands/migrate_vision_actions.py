"""Migrate legacy VisionActions onto the alerts and scouts systems, org by org.

Dry-run by default. For each organization with eligible actions:

- `mode=alert` actions become VisionAlertConfigurations (every_match -> match kind,
  on_breach -> metric kind), with their Slack/webhook targets rebuilt as alert
  destinations. A legacy alert overriding `selection.scanner_ids` becomes one new
  alert per scanner.
- Hand-made group summaries and default digests with deliveries become scanner
  scouts via the signals facade.
- Delivery-less default digests are disabled in place; the in-app card is served
  by the new system.
- The organization is appended to the rollout flags, so its users switch surface
  the moment their data lands.

Every touched row is stamped with a `migrated_to` pointer (or `retired`), which
makes the command idempotent and the cutover scriptably reversible.
"""

import os
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

import requests
import structlog

from posthog.models import Team, User

from products.replay_vision.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    MATCH_EVENT_KINDS,
    METRIC_EVENT_KINDS,
    VISION_ALERT_EVENT_IDS,
    VISION_ALERT_SLACK_CONTEXT_ELEMENTS,
)
from products.replay_vision.backend.api.vision_actions_shim import _parse_rrule, rrule_to_cron
from products.replay_vision.backend.models.vision_action import ActionMode, AlertFrequency, VisionAction
from products.replay_vision.backend.models.vision_alert import (
    ALERT_WINDOW_DAYS,
    VisionAlertConfiguration,
    VisionAlertDirection,
    VisionAlertKind,
    VisionAlertMetric,
)
from products.replay_vision.backend.scout_digest_body import compose_digest_scout_body
from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT

logger = structlog.get_logger(__name__)

ALERTS_FLAG_KEY = "replay-vision-alerts"
SCOUTS_FLAG_KEY = "replay-vision-scout-digests"

# Legacy on_breach alerts were evaluated at their action's schedule cadence; the new
# scheduler takes a minute interval instead.
_FREQ_TO_MINUTES = {"MINUTELY": 15, "HOURLY": 60, "DAILY": 1440, "WEEKLY": 10080}


FLAGS_API_KEY_ENV = "POSTHOG_FLAGS_API_KEY"


class _FlagsApiTargeting:
    """Widens org targeting on flags that live on another PostHog instance.

    EU evaluates the rollout flags against the US instance (`posthog.ph_client` self-capture), so a
    migration run on EU must widen the US flags. Each widen re-reads the flag before the PATCH: the
    run is long, and writing back a cached filters document would revert any concurrent flag edit.
    """

    def __init__(self, host: str, project_id: int, api_key: str) -> None:
        self._host = host.rstrip("/")
        self._base = f"{self._host}/api/projects/{project_id}/feature_flags"
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_key}"
        self._flag_ids: dict[str, int] = {}

    @property
    def where(self) -> str:
        return self._host

    def preflight(self, keys: tuple[str, ...]) -> None:
        """Resolve flag ids so a wrong host, key, or missing flag fails before any row is migrated."""
        for key in keys:
            response = self._session.get(self._base, params={"key": key}, timeout=15)
            response.raise_for_status()
            results = response.json().get("results", [])
            flag = next((f for f in results if f.get("key") == key and not f.get("deleted")), None)
            if flag is None or flag.get("id") is None:
                raise CommandError(f"flag {key}: not found via {self._base}")
            self._flag_ids[key] = flag["id"]

    def add_group(self, key: str, group_key: str) -> str | None:
        """Widen one flag's org targeting. Returns a problem description, or None on success."""
        url = f"{self._base}/{self._flag_ids[key]}/"
        try:
            response = self._session.get(url, timeout=15)
            response.raise_for_status()
            filters = response.json().get("filters") or {}
            # Mirrors add_group_to_flag_targeting in the feature flags facade; keep in sync.
            conditions = [
                prop
                for group in filters.get("groups") or []
                for prop in group.get("properties", [])
                if prop.get("key") == "$group_key"
            ]
            if not conditions:
                return "no organization targeting to widen"
            values = conditions[0].get("value")
            if not isinstance(values, list):
                return "no organization targeting to widen"
            if group_key not in values:
                values.append(group_key)
                self._session.patch(url, json={"filters": filters}, timeout=15).raise_for_status()
            return None
        except requests.RequestException as error:
            logger.exception("vision_action_migration.flags_api_failed", key=key, error=str(error))
            return f"API request failed ({error})"


class _LocalFlagTargeting:
    """The same widen contract over this instance's own flags project."""

    def __init__(self, team: Team) -> None:
        self._team = team

    @property
    def where(self) -> str:
        return f"team {self._team.id}"

    def add_group(self, key: str, group_key: str) -> str | None:
        from products.feature_flags.backend.facade.api import (  # noqa: PLC0415 — keeps the flags API surface off the command's import path
            add_group_to_flag_targeting,
        )

        if add_group_to_flag_targeting(team=self._team, key=key, group_key=group_key):
            return None
        return "no organization targeting to widen"


_FlagTargeting = _FlagsApiTargeting | _LocalFlagTargeting


@dataclass(frozen=False)
class _Report:
    alerts_created: int = 0
    scouts_created: int = 0
    defaults_retired: int = 0
    skipped_already: int = 0
    orgs_flagged: int = 0
    problems: list[str] = field(default_factory=list)


def _clean_selection(selection: dict | None) -> dict:
    """Legacy selections already use the new predicate keys; strip what moved elsewhere."""
    selection = dict(selection or {})
    selection.pop("scanner_ids", None)
    selection.pop("window_days", None)
    selection.pop("status", None)
    return {k: v for k, v in selection.items() if v not in (None, [], "")}


def _destination_data(entry: dict) -> dict | None:
    if entry.get("type") == "slack":
        channel = str(entry.get("channel") or "")
        channel_id, _, channel_name = channel.partition("|")
        return {
            "type": "slack",
            "slack_workspace_id": entry.get("integration_id"),
            "slack_channel_id": channel_id,
            "slack_channel_name": channel_name or channel_id,
        }
    if entry.get("type") == "webhook":
        url = entry.get("url")
        if url:
            return {"type": "webhook", "webhook_url": url}
    return None


def _acting_user(action: VisionAction) -> User | None:
    if action.created_by is not None:
        return action.created_by
    membership = action.team.organization.memberships.filter(user__is_active=True).order_by("joined_at").first()
    return membership.user if membership else None


def _unique_name(team_id: int, base: str) -> str:
    name = base
    suffix = 2
    while VisionAlertConfiguration.objects.for_team(team_id).filter(name=name).exists():
        name = f"{base} ({suffix})"
        suffix += 1
    return name


def _scout_slug(action: VisionAction) -> str:
    # The action-id suffix makes the name deterministic and collision-free, so a re-run
    # upserts the same scout instead of creating a duplicate or clobbering a neighbor.
    slug = re.sub(r"[^a-z0-9-]+", "-", action.name.lower()).strip("-")[:34] or "digest"
    return f"signals-scout-{slug}-{str(action.id).replace('-', '')[-6:]}"


class Command(BaseCommand):
    help = "Migrate legacy VisionActions to the new alerts and scouts systems. Dry-run unless --execute."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--execute", action="store_true", help="Apply changes. Without it, print the plan.")
        parser.add_argument("--org", action="append", default=[], help="Only these organization ids (repeatable).")
        parser.add_argument(
            "--flag-team-id",
            type=int,
            default=None,
            help="Team id of this instance's internal flags project (US: 2). Mutually exclusive with --flags-api-host.",
        )
        parser.add_argument(
            "--flags-api-host",
            default=None,
            help="Widen the rollout flags over the REST API of this PostHog instance instead of the local ORM. "
            "Use from EU: the flags live on the US instance. Requires --flags-api-project and "
            f"a personal API key with feature flag write scope in ${FLAGS_API_KEY_ENV}.",
        )
        parser.add_argument(
            "--flags-api-project",
            type=int,
            default=None,
            help="Project id holding the rollout flags on --flags-api-host (US: 2).",
        )
        parser.add_argument("--limit-orgs", type=int, default=None, help="Stop after this many organizations.")

    def handle(self, *args: Any, **options: Any) -> None:
        execute: bool = options["execute"]
        api_mode = options["flags_api_host"] is not None or options["flags_api_project"] is not None
        if api_mode and (options["flags_api_host"] is None or options["flags_api_project"] is None):
            raise CommandError("--flags-api-host and --flags-api-project must be passed together.")
        if api_mode == (options["flag_team_id"] is not None):
            raise CommandError("Pass exactly one of --flag-team-id or --flags-api-host/--flags-api-project.")
        targeting: _FlagTargeting
        if api_mode:
            api_key = os.environ.get(FLAGS_API_KEY_ENV)
            if not api_key:
                raise CommandError(f"--flags-api-host requires a personal API key in ${FLAGS_API_KEY_ENV}.")
            if not options["flags_api_host"].startswith("https://"):
                raise CommandError("--flags-api-host must be https:// — the API key crosses the network.")
            api_targeting = _FlagsApiTargeting(options["flags_api_host"], options["flags_api_project"], api_key)
            try:
                # Runs in dry-run mode too, so a rehearsal validates the host, key, and flags.
                api_targeting.preflight((ALERTS_FLAG_KEY, SCOUTS_FLAG_KEY))
            except requests.RequestException as error:
                raise CommandError(f"flags API preflight failed: {error}")
            targeting = api_targeting
        else:
            targeting = _LocalFlagTargeting(Team.objects.get(id=options["flag_team_id"]))
        report = _Report()

        actions = (
            VisionAction.objects.unscoped()
            .filter(mode__in=[ActionMode.ALERT, ActionMode.GROUP_SUMMARY])
            .select_related("team", "team__organization", "scanner", "created_by")
            .order_by("team__organization_id", "team_id", "created_at")
        )
        if options["org"]:
            actions = actions.filter(team__organization_id__in=options["org"])

        by_org: dict[Any, list[VisionAction]] = {}
        for action in actions:
            by_org.setdefault(action.team.organization_id, []).append(action)

        orgs = list(by_org.items())
        if options["limit_orgs"]:
            orgs = orgs[: options["limit_orgs"]]

        for org_id, org_actions in orgs:
            self._migrate_org(org_id, org_actions, execute, targeting, report)

        mode = "EXECUTED" if execute else "DRY RUN"
        self.stdout.write(
            f"[{mode}] orgs: {len(orgs)} | alerts created: {report.alerts_created} | "
            f"scouts created: {report.scouts_created} | defaults retired: {report.defaults_retired} | "
            f"already migrated (skipped): {report.skipped_already} | orgs flagged: {report.orgs_flagged}"
        )
        for problem in report.problems:
            self.stdout.write(f"  PROBLEM: {problem}")
        if report.problems and execute:
            raise CommandError(f"{len(report.problems)} rows need manual attention; see above.")

    def _migrate_org(
        self, org_id: Any, org_actions: list[VisionAction], execute: bool, targeting: _FlagTargeting, report: _Report
    ) -> None:
        # "This org has migrated rows", not "this run migrated something": an interrupted run that
        # already moved the rows must still be able to flag the org on a re-run, or its users sit on
        # the legacy surface with their legacy actions disabled — no alerting at all.
        migrated_any = False
        org_problems = 0
        pending: list[VisionAction] = []
        for action in org_actions:
            stamp_field = "alert_config" if action.mode == ActionMode.ALERT else "synthesis_config"
            stamps = getattr(action, stamp_field) or {}
            if stamps.get("migrated_to") or stamps.get("retired"):
                report.skipped_already += 1
                migrated_any = True
                continue
            pending.append(action)

        # Check the whole organization before writing any of it. A row that fails halfway through
        # otherwise leaves the org part-migrated and unflagged: some rows moved, the rest still
        # live on the legacy surface, and nobody switched over.
        blockers = [problem for action in pending if (problem := self._validation_problem(action))]
        if blockers:
            for problem in blockers:
                report.problems.append(problem)
            report.problems.append(f"org {org_id}: not migrated, {len(blockers)} row(s) need attention")
            return

        for action in pending:
            try:
                plan = self._plan(action)
                if plan == "alert":
                    migrated_any |= self._migrate_alert(action, execute, report)
                elif plan == "digest":
                    migrated_any |= self._migrate_digest(action, execute, report)
                else:
                    # Retiring a default is a completed migration for that row: the new Overview
                    # card replaces it. Without feeding the flag flip, an org whose only rows are
                    # default digests gets them disabled and never switches surface, so its
                    # Overview reads "The featured digest is paused." forever.
                    migrated_any |= self._retire_default(action, execute, report)
            except Exception as error:
                org_problems += 1
                report.problems.append(f"{action.mode} {action.id} ({action.name!r}, team {action.team_id}): {error}")
                logger.exception("vision_action_migration.row_failed", action_id=str(action.id))

        if org_problems:
            # Flagging now would put the org on the new surface while the failed row's legacy action
            # is still enabled on the old one — the double-notification case.
            report.problems.append(f"org {org_id}: not flagged, {org_problems} row(s) need attention")
            return
        if migrated_any:
            self._flag_org(org_id, execute, targeting, report)

    def _plan(self, action: VisionAction) -> str:
        """What this row becomes. Shared by the check and the write so they cannot disagree."""
        if action.mode == ActionMode.ALERT:
            return "alert"
        if action.delivery_config or not action.is_scanner_digest:
            return "digest"
        return "retire"

    def _validation_problem(self, action: VisionAction) -> str | None:
        """Why this row cannot migrate, or None. Reads only; never writes."""
        where = f"{action.mode} {action.id} ({action.name!r}, team {action.team_id})"
        plan = self._plan(action)
        if plan == "retire":
            return None
        if _acting_user(action) is None and (plan == "digest" or action.delivery_config):
            return f"{where}: no active user in the organization to own the migrated row"
        if plan == "digest":
            try:
                rrule_to_cron((action.trigger_config or {}).get("rrule") or "FREQ=DAILY;BYHOUR=8;BYMINUTE=0")
            except ValueError as error:
                return f"{where}: {error}"
        return None

    def _migrate_alert(self, action: VisionAction, execute: bool, report: _Report) -> bool:
        config = action.alert_config or {}
        frequency = config.get("frequency", AlertFrequency.EVERY_MATCH)
        selection = action.selection or {}
        scanner_ids = selection.get("scanner_ids") or [str(action.scanner_id)]
        acting = _acting_user(action)

        new_ids: list[str] = []
        staged: list[dict[str, Any]] = []
        for index, scanner_id in enumerate(scanner_ids):
            base = action.name if len(scanner_ids) == 1 else f"{action.name} ({index + 1})"
            kwargs: dict[str, Any] = {
                "team_id": action.team_id,
                "scanner_id": scanner_id,
                "name": _unique_name(action.team_id, base),
                "enabled": action.enabled,
                "created_by": action.created_by,
                "first_enabled_at": action.created_at,
                "selection": _clean_selection(selection),
            }
            if frequency == AlertFrequency.ON_BREACH:
                window = int(config.get("window_days") or 1)
                if window not in ALERT_WINDOW_DAYS:
                    window = min(ALERT_WINDOW_DAYS, key=lambda choice: abs(choice - window))
                cadence = _FREQ_TO_MINUTES.get(
                    _parse_rrule((action.trigger_config or {}).get("rrule", "")).get("FREQ", ""), 1440
                )
                kwargs.update(
                    kind=VisionAlertKind.METRIC,
                    metric=config.get("metric", VisionAlertMetric.COUNT),
                    direction=config.get("direction", VisionAlertDirection.ABOVE),
                    threshold=float(config.get("threshold", 1)),
                    window_days=window,
                    check_interval_minutes=max(cadence, 15),
                )
            else:
                kwargs.update(kind=VisionAlertKind.MATCH, threshold=None)

            if not execute:
                new_ids.append("(dry-run)")
                continue
            staged.append(kwargs)
        report.alerts_created += len(scanner_ids)

        if not execute:
            return True
        # One transaction for every alert this action becomes AND its stamp: a partial commit would
        # leave unstamped alerts that a re-run duplicates, and both copies would then fire.
        with transaction.atomic():
            for kwargs in staged:
                alert = VisionAlertConfiguration.objects.for_team(action.team_id).create(**kwargs)
                self._create_destinations(alert, action, acting)
                new_ids.append(str(alert.id))
            action.alert_config = {**config, "migrated_to": new_ids, "migrated_at": timezone.now().isoformat()}
            action.enabled = False
            action.save(update_fields=["alert_config", "enabled", "updated_at"])
        return True

    def _create_destinations(self, alert: VisionAlertConfiguration, action: VisionAction, acting: User | None) -> None:
        from products.alerts.backend.destination_configs import (  # noqa: PLC0415 — keeps the alerts API surface off the command's import path
            AlertDestinationData,
            DestinationType,
        )
        from products.alerts.backend.facade.api import (  # noqa: PLC0415 — keeps the alerts API surface off the command's import path
            build_alert_destination_config,
            create_alert_destination_hog_functions,
        )

        entries = [data for data in (_destination_data(entry) for entry in action.delivery_config or []) if data]
        if not entries or acting is None:
            if entries and acting is None:
                raise ValueError("no acting user available to own the destination hog functions")
            return
        kinds = MATCH_EVENT_KINDS if alert.kind == VisionAlertKind.MATCH else METRIC_EVENT_KINDS
        request = SimpleNamespace(user=acting)
        for data in entries:
            destination = cast("AlertDestinationData", {**data, "type": DestinationType(data["type"])})
            configs = [
                build_alert_destination_config(
                    team=alert.team,
                    spec=EVENT_KIND_CONFIG[kind],
                    alert_id=str(alert.id),
                    alert_name=alert.name,
                    data=destination,
                    slack_context_elements=VISION_ALERT_SLACK_CONTEXT_ELEMENTS,
                )
                for kind in kinds
            ]
            create_alert_destination_hog_functions(
                configs, request=request, alert_id=str(alert.id), allowed_event_ids=VISION_ALERT_EVENT_IDS
            )

    def _migrate_digest(self, action: VisionAction, execute: bool, report: _Report) -> bool:
        from products.signals.backend.facade import (  # noqa: PLC0415 — keeps the signals API surface off the command's import path
            api as signals_facade,
        )

        acting = _acting_user(action)
        if acting is None:
            raise ValueError("no acting user available to own the scout")
        cron = rrule_to_cron((action.trigger_config or {}).get("rrule") or "FREQ=DAILY;BYHOUR=8;BYMINUTE=0")

        destinations: dict[str, Any] = {}
        for entry in action.delivery_config or []:
            data = _destination_data(entry)
            if not data:
                continue
            if data["type"] == "slack" and "slack" not in destinations:
                destinations["slack"] = {
                    "integration_id": data["slack_workspace_id"],
                    "channel_id": data["slack_channel_id"],
                    "channel_name": data["slack_channel_name"],
                }
            elif data["type"] == "webhook" and "webhook" not in destinations:
                destinations["webhook"] = {"url": data["webhook_url"]}

        payload: dict[str, Any] = {
            "name": _scout_slug(action),
            "description": f'Migrated Replay Vision digest "{action.name}" for scanner "{action.scanner.name}".',
            "body": compose_digest_scout_body(
                str(action.scanner_id),
                selection=action.selection,
                prompt_guide=(action.synthesis_config or {}).get("prompt_guide"),
                max_observations=action.max_observations,
            ),
            "config": {
                "enabled": action.enabled,
                "run_cron_schedule": cron,
                **({"output_destinations": destinations} if destinations else {}),
            },
        }

        report.scouts_created += 1
        if not execute:
            return True

        with transaction.atomic():
            signals_facade.create_scout_for_source(
                team=action.team.parent_team or action.team,
                user=acting,
                name=payload["name"],
                description=payload["description"],
                body=payload["body"],
                files=[],
                config_options=payload["config"],
                request=SimpleNamespace(user=acting),
                serializer_context={"project_id": action.team.project_id},
                source_product=SCOUT_SOURCE_PRODUCT,
                source_id=str(action.scanner_id),
            )
            action.synthesis_config = {
                **(action.synthesis_config or {}),
                "migrated_to": payload["name"],
                "migrated_at": timezone.now().isoformat(),
            }
            action.enabled = False
            action.save(update_fields=["synthesis_config", "enabled", "updated_at"])
            logger.info("vision_action_migration.scout_created", action_id=str(action.id), scout=payload["name"])
        return True

    def _retire_default(self, action: VisionAction, execute: bool, report: _Report) -> bool:
        report.defaults_retired += 1
        if not execute:
            return True
        action.synthesis_config = {**(action.synthesis_config or {}), "retired": True}
        action.enabled = False
        action.save(update_fields=["synthesis_config", "enabled", "updated_at"])
        return True

    def _flag_org(self, org_id: Any, execute: bool, targeting: _FlagTargeting, report: _Report) -> None:
        widened = True
        for key in (ALERTS_FLAG_KEY, SCOUTS_FLAG_KEY):
            if not execute:
                continue
            problem = targeting.add_group(key, str(org_id))
            if problem is not None:
                report.problems.append(f"flag {key}: {problem} on {targeting.where}")
                widened = False
        # Counting the org as flagged when a flag never took would report a rollout that did not
        # happen, and its users would sit on the legacy surface with their rows already migrated.
        if widened:
            report.orgs_flagged += 1
