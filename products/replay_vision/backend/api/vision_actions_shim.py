"""Serve the legacy vision-actions API surface from the new alerts and scouts systems.

Once an organization is on the `replay-vision-alerts` flag, the legacy endpoints stop touching
`VisionAction` rows: creates become alerts or scouts, reads synthesize legacy-shaped responses
from the new entities, and updates and deletes resolve ids across all three id spaces (new alert
uuids, scout config ids, and migrated legacy row ids via their `migrated_to` stamps). Existing
MCP and agent callers keep their contract without knowing anything moved.
"""

import re
import uuid
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import NotFound, ValidationError

from posthog.api.shared import UserBasicSerializer
from posthog.models import Team, User

from products.alerts.backend.destination_configs import AlertDestinationData, DestinationType
from products.alerts.backend.destinations import owned_alert_destinations_qs
from products.alerts.backend.facade.api import (
    build_alert_destination_config,
    create_alert_destination_hog_functions,
    soft_delete_all_alert_destinations,
)
from products.alerts.backend.state_machine import apply_disable, apply_enable, apply_threshold_change
from products.replay_vision.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    MATCH_EVENT_KINDS,
    METRIC_EVENT_KINDS,
    VISION_ALERT_EVENT_IDS,
    VISION_ALERT_SLACK_CONTEXT_ELEMENTS,
)
from products.replay_vision.backend.alert_state_machine import apply_outcome
from products.replay_vision.backend.models.vision_action import ActionMode, VisionAction
from products.replay_vision.backend.models.vision_alert import (
    VisionAlertConfiguration,
    VisionAlertEvent,
    VisionAlertKind,
)
from products.replay_vision.backend.scout_digest_body import compose_digest_scout_body
from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT
from products.signals.backend.facade import api as signals_facade
from products.signals.backend.facade.api import ScoutSummary

MAX_ENABLED_ALERTS_PER_SCANNER = 10

_CRON_DAY_TO_RRULE = {"0": "SU", "1": "MO", "2": "TU", "3": "WE", "4": "TH", "5": "FR", "6": "SA", "7": "SU"}


def redact_webhook_url(url: str) -> str:
    # Show the scheme + host so a viewer can see *where* it delivers, but drop everything a credential
    # can hide in: the path, the query, AND any `user:pass@` userinfo (which `netloc` would carry, so
    # rebuild the authority from hostname/port only). IPv6 hosts keep their brackets. Falls back to a
    # fully-opaque marker if the URL can't be parsed.
    parsed = urlparse(url)
    if parsed.scheme and parsed.hostname:
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        authority = f"{host}:{parsed.port}" if parsed.port else host
        return f"{parsed.scheme}://{authority}/…"
    return "(hidden)"


def unmigrated(queryset: Any) -> Any:
    """Legacy rows the migration has not moved.

    A migrated row is disabled and its successor is live, so listing it invites someone to
    re-enable it, which re-arms the legacy sweep and its destinations alongside the new alert.
    """
    return (
        queryset.exclude(alert_config__has_key="migrated_to")
        .exclude(synthesis_config__has_key="migrated_to")
        .exclude(synthesis_config__has_key="retired")
    )


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _user_basic(user_id: int | None) -> dict[str, Any] | None:
    """The legacy surface rendered `created_by` through UserBasicSerializer, not as a bare id."""
    if user_id is None:
        return None
    user = User.objects.filter(id=user_id).first()
    return UserBasicSerializer(user).data if user is not None else None


_DAY_TO_CRON = {"SU": 0, "MO": 1, "TU": 2, "WE": 3, "TH": 4, "FR": 5, "SA": 6}


def _parse_rrule(rrule: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in rrule.split(";") if "=" in part)


def rrule_to_cron(rrule: str) -> str:
    """Convert the legacy schedule rrules seen in production to cron.

    Covers FREQ=DAILY/WEEKLY(+BYDAY)+BYHOUR/BYMINUTE, FREQ=HOURLY, and FREQ=MINUTELY;INTERVAL=n.
    Anything else raises so the caller can surface it instead of storing a wrong schedule.
    """
    parts = _parse_rrule(rrule)
    freq = parts.get("FREQ")
    minute = parts.get("BYMINUTE", "0")
    hour = parts.get("BYHOUR", "8")
    if freq == "MINUTELY":
        interval = int(parts.get("INTERVAL", "15"))
        return f"*/{max(interval, 15)} * * * *"
    if freq == "HOURLY":
        return "0 * * * *"
    if freq == "DAILY":
        if parts.get("INTERVAL", "1") != "1":
            raise ValueError(f"Cron cannot express a multi-day interval: {rrule}")
        return f"{minute} {hour} * * *"
    if freq == "WEEKLY":
        # cron repeats every week, so an INTERVAL would silently double the cadence.
        if parts.get("INTERVAL", "1") != "1":
            raise ValueError(f"Cron cannot express a multi-week interval: {rrule}")
        days = parts.get("BYDAY")
        if not days:
            return f"{minute} {hour} * * 1"
        tokens = days.split(",")
        # rrule accepts ordinal tokens like 1MO ("first Monday"); cron has no equivalent.
        unknown = [token for token in tokens if token not in _DAY_TO_CRON]
        if unknown:
            raise ValueError(f"Unsupported BYDAY token(s) {unknown} in rrule: {rrule}")
        return f"{minute} {hour} * * {','.join(str(_DAY_TO_CRON[token]) for token in tokens)}"
    raise ValueError(f"Unsupported rrule: {rrule}")


def cron_to_rrule(cron: str | None) -> str:
    """Best-effort inverse of the migration's rrule->cron conversion, for representation only."""
    if not cron:
        return "FREQ=DAILY;BYHOUR=8;BYMINUTE=0"
    parts = cron.split()
    if len(parts) != 5:
        return "FREQ=DAILY;BYHOUR=8;BYMINUTE=0"
    minute, hour, _dom, _month, dow = parts
    if minute.startswith("*/"):
        return f"FREQ=MINUTELY;INTERVAL={minute[2:]}"
    if hour == "*":
        return "FREQ=HOURLY"
    if dow == "*":
        return f"FREQ=DAILY;BYHOUR={hour};BYMINUTE={minute}"
    days = ",".join(_CRON_DAY_TO_RRULE.get(day, "MO") for day in dow.split(","))
    return f"FREQ=WEEKLY;BYDAY={days};BYHOUR={hour};BYMINUTE={minute}"


def _delivery_configs_for_alerts(
    team_id: int, alert_ids: list[str], *, can_edit: bool
) -> dict[str, list[dict[str, Any]]]:
    """Delivery targets for many alerts in one query, keyed by alert id.

    The list endpoint renders every alert on the team, so a per-alert query here is one round trip
    per row.
    """
    by_alert: dict[str, list[dict[str, Any]]] = {alert_id: [] for alert_id in alert_ids}
    if not alert_ids:
        return by_alert
    seen: set[tuple[Any, ...]] = set()
    hog_functions = owned_alert_destinations_qs(
        team_id=team_id, alert_ids=alert_ids, allowed_event_ids=VISION_ALERT_EVENT_IDS
    ).filter(enabled=True)
    for hog_function in hog_functions:
        properties = (hog_function.filters or {}).get("properties") or []
        alert_id = next((p.get("value") for p in properties if p.get("key") == "alert_id"), None)
        if alert_id not in by_alert:
            continue
        target = _render_destination(hog_function, seen, can_edit=can_edit)
        if target is not None:
            by_alert[str(alert_id)].append(target)
    return by_alert


def _render_destination(hog_function: Any, seen: set[tuple[Any, ...]], *, can_edit: bool) -> dict[str, Any] | None:
    """One legacy delivery target, or None when it duplicates one already rendered.

    A webhook URL can carry a bearer token, so it stays redacted for readers without edit access,
    the same bar the legacy representation applied.
    """
    inputs = hog_function.inputs or {}
    template_id = hog_function.template_id or ""
    if "slack" in template_id:
        channel = (inputs.get("channel") or {}).get("value")
        integration = (inputs.get("slack_workspace") or {}).get("value")
        key = ("slack", integration, channel)
        if not channel or key in seen:
            return None
        seen.add(key)
        return {"type": "slack", "integration_id": integration, "channel": channel}
    url = (inputs.get("url") or {}).get("value")
    key = ("webhook", url, None)
    if not url or key in seen:
        return None
    seen.add(key)
    return {"type": "webhook", "url": url if can_edit else redact_webhook_url(url)}


def _delivery_config_for_alert(alert: VisionAlertConfiguration, *, can_edit: bool = True) -> list[dict[str, Any]]:
    return _delivery_configs_for_alerts(alert.team_id, [str(alert.id)], can_edit=can_edit)[str(alert.id)]


def _scout_delivery_config(summary: ScoutSummary, *, can_edit: bool = True) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    destinations = summary.output_destinations or {}
    slack = destinations.get("slack")
    if slack:
        channel = slack.get("channel_id", "")
        name = slack.get("channel_name")
        targets.append(
            {
                "type": "slack",
                "integration_id": slack.get("integration_id"),
                "channel": f"{channel}|{name}" if name else channel,
            }
        )
    webhook = destinations.get("webhook")
    if webhook and webhook.get("url"):
        url = webhook["url"]
        targets.append({"type": "webhook", "url": url if can_edit else redact_webhook_url(url)})
    return targets


def render_alert_as_action(
    alert: VisionAlertConfiguration, *, can_edit: bool = True, delivery_config: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    if alert.kind == VisionAlertKind.MATCH:
        alert_config: dict[str, Any] = {"frequency": "every_match", "metric": alert.metric or "count"}
    else:
        alert_config = {
            "frequency": "on_breach",
            "metric": alert.metric,
            "direction": alert.direction,
            "threshold": alert.threshold,
            "window_days": alert.window_days,
        }
    return {
        "id": str(alert.id),
        "name": alert.name,
        "enabled": alert.enabled,
        "mode": ActionMode.ALERT,
        "is_scanner_digest": False,
        "trigger_type": "schedule",
        "trigger_config": {},
        "scanner": str(alert.scanner_id),
        "selection": alert.selection or {},
        "synthesis_config": {},
        "alert_config": alert_config,
        "delivery_config": (
            delivery_config if delivery_config is not None else _delivery_config_for_alert(alert, can_edit=can_edit)
        ),
        "hog_flow": None,
        "next_run_at": alert.next_check_at.isoformat() if alert.next_check_at else None,
        "last_run_at": alert.last_checked_at.isoformat() if alert.last_checked_at else None,
        "created_at": alert.created_at.isoformat(),
        "created_by": _user_basic(alert.created_by_id),
        "updated_at": alert.updated_at.isoformat(),
    }


def render_scout_as_action(summary: ScoutSummary, *, can_edit: bool = True) -> dict[str, Any]:
    return {
        "id": summary.config_id,
        "name": summary.skill_name,
        "enabled": summary.enabled,
        "mode": ActionMode.GROUP_SUMMARY,
        "is_scanner_digest": False,
        "trigger_type": "schedule",
        "trigger_config": {"rrule": cron_to_rrule(summary.run_cron_schedule), "timezone": "UTC"},
        "scanner": summary.source_id,
        "selection": {},
        "synthesis_config": {"prompt_guide": summary.description},
        "alert_config": {},
        "delivery_config": _scout_delivery_config(summary, can_edit=can_edit),
        "hog_flow": None,
        "next_run_at": None,
        "last_run_at": summary.last_run_at.isoformat() if summary.last_run_at else None,
        "created_at": summary.created_at.isoformat() if summary.created_at else None,
        "created_by": _user_basic(summary.created_by_id),
        "updated_at": None,
    }


def list_actions(
    team: Team, scanner_ids: list[str], *, editable_scanner_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    """Every alert and scout on the caller's accessible scanners, in the legacy shape.

    `scanner_ids` is the caller's accessible set and `editable_scanner_ids` the subset they may
    edit, both resolved by the viewset. An empty accessible set means nothing is visible, so the
    surface stays closed rather than falling back to "all". Edit access is per scanner because a
    resource-level editor can still hold an object-level restriction on one scanner, and that
    scanner's webhook URLs must stay redacted for them.
    """
    editable = editable_scanner_ids if editable_scanner_ids is not None else set(scanner_ids)
    if not scanner_ids:
        return []
    alerts = (
        VisionAlertConfiguration.objects.for_team(team.id)
        .filter(scanner_id__in=scanner_ids)
        .select_related("scanner")
        .order_by("created_at")
    )
    scouts = signals_facade.list_scouts_for_source(
        (team.parent_team or team).id, SCOUT_SOURCE_PRODUCT, source_ids=scanner_ids
    )
    alert_rows = list(alerts)
    deliveries = {
        **_delivery_configs_for_alerts(
            team.id, [str(a.id) for a in alert_rows if str(a.scanner_id) in editable], can_edit=True
        ),
        **_delivery_configs_for_alerts(
            team.id, [str(a.id) for a in alert_rows if str(a.scanner_id) not in editable], can_edit=False
        ),
    }
    return [
        render_alert_as_action(
            alert, can_edit=str(alert.scanner_id) in editable, delivery_config=deliveries.get(str(alert.id))
        )
        for alert in alert_rows
    ] + [render_scout_as_action(scout, can_edit=str(scout.source_id) in editable) for scout in scouts]


def _resolve(team: Team, pk: str) -> tuple[str, Any] | None:
    """Resolve an id from any of the three id spaces to ('alert', obj) or ('scout', summary).

    A digest's `migrated_to` stamp is its scout *name*, not a uuid, so every uuid-column lookup is
    guarded — an unguarded filter raises on a name before the name lookup is ever reached.
    """
    if _is_uuid(pk):
        alert = VisionAlertConfiguration.objects.for_team(team.id).filter(id=pk).first()
        if alert is not None:
            return ("alert", alert)
    for scout in signals_facade.list_scouts_for_source((team.parent_team or team).id, SCOUT_SOURCE_PRODUCT):
        if pk in (scout.config_id, scout.skill_name):
            return ("scout", scout)
    if not _is_uuid(pk):
        return None
    legacy = VisionAction.objects.for_team(team.id).filter(id=pk).first()
    if legacy is None:
        return None
    stamps = (legacy.alert_config or {}) if legacy.mode == ActionMode.ALERT else (legacy.synthesis_config or {})
    migrated = stamps.get("migrated_to")
    if isinstance(migrated, list):
        migrated = migrated[0] if migrated else None
    return _resolve(team, str(migrated)) if migrated else None


def resolve_entities(team: Team, pk: str) -> list[tuple[str, Any]]:
    """Every entity an id stands for.

    A legacy alert overriding `selection.scanner_ids` migrated into one alert per scanner, so its
    id names all of them. Acting on only the first would leave the rest enabled.
    """
    if not _is_uuid(pk):
        single = _resolve(team, pk)
        return [single] if single else []
    legacy = VisionAction.objects.for_team(team.id).filter(id=pk).first()
    if legacy is not None:
        stamps = (legacy.alert_config or {}) if legacy.mode == ActionMode.ALERT else (legacy.synthesis_config or {})
        migrated = stamps.get("migrated_to")
        if isinstance(migrated, list):
            resolved = [_resolve(team, str(successor)) for successor in migrated]
            return [entry for entry in resolved if entry is not None]
    single = _resolve(team, pk)
    return [single] if single else []


def scanner_ids_for_entities(entries: list[tuple[str, Any]]) -> list[str]:
    """Every scanner the given entities live on, so all of them can be object-checked.

    Takes resolved entities rather than an id: authorizing a second resolution of the same id
    would leave room for the check and the write to disagree, which is how a fanned-out alert
    once had only its first successor checked.
    """
    ids: list[str] = []
    for kind, entity in entries:
        scanner_id = str(entity.scanner_id) if kind == "alert" else entity.source_id
        if scanner_id and scanner_id not in ids:
            ids.append(scanner_id)
    return ids


def render_entity(entry: tuple[str, Any], *, can_edit: bool = True) -> dict[str, Any]:
    kind, entity = entry
    if kind == "alert":
        return render_alert_as_action(entity, can_edit=can_edit)
    return render_scout_as_action(entity, can_edit=can_edit)


def create_action(team: Team, user: User, data: dict[str, Any]) -> dict[str, Any]:
    """Create the new-system entity a legacy create asks for.

    `data` must be validated legacy payload — the viewset runs it through `VisionActionSerializer`
    first, which is what team-scopes the scanner, checks integration ownership on Slack targets,
    enforces https-only webhooks, and applies the selection allowlist. Nothing here re-derives
    those, so callers must not hand it raw request data.
    """
    mode = data.get("mode", ActionMode.GROUP_SUMMARY)
    if mode == ActionMode.ALERT:
        return _create_alert(team, user, data)
    if mode == ActionMode.GROUP_SUMMARY:
        return _create_scout(team, user, data)
    raise ValidationError({"mode": f"Unsupported mode {mode!r}."})


def _validated_scanner_id(data: dict[str, Any]) -> str:
    """The scanner from an already-validated payload, where it arrives as the model instance."""
    scanner = data.get("scanner") or data.get("scanner_id")
    if scanner is None:
        raise ValidationError({"scanner": "This field is required."})
    return str(getattr(scanner, "id", scanner))


def _legacy_destination_data(entry: dict[str, Any]) -> "AlertDestinationData | None":
    if entry.get("type") == "slack":
        channel = str(entry.get("channel") or "")
        channel_id, _, channel_name = channel.partition("|")
        return cast(
            "AlertDestinationData",
            {
                "type": DestinationType.SLACK,
                "slack_workspace_id": entry.get("integration_id"),
                "slack_channel_id": channel_id,
                "slack_channel_name": channel_name or channel_id,
            },
        )
    if entry.get("type") == "webhook" and entry.get("url"):
        return cast("AlertDestinationData", {"type": DestinationType.WEBHOOK, "webhook_url": entry["url"]})
    return None


def _enforce_enabled_alert_cap(team: Team, scanner_id: str, *, exclude_id: str | None = None) -> None:
    """The legacy serializer's per-scanner cap, counted on the table the shim actually writes.

    `VisionActionSerializer._validate_alert_cap` counts VisionAction rows, and the shim creates
    none, so the cap it enforces is vacuous here. Alerts evaluate on the scanner's sweep, so the
    fan-out this bounds is real work.
    """
    others = VisionAlertConfiguration.objects.for_team(team.id).filter(scanner_id=scanner_id, enabled=True)
    if exclude_id is not None:
        others = others.exclude(id=exclude_id)
    if others.count() >= MAX_ENABLED_ALERTS_PER_SCANNER:
        raise ValidationError(
            {"enabled": f"A scanner can have at most {MAX_ENABLED_ALERTS_PER_SCANNER} enabled alerts."}
        )


def _create_alert(team: Team, user: User, data: dict[str, Any]) -> dict[str, Any]:
    config = data.get("alert_config") or {}
    frequency = config.get("frequency", "every_match")
    scanner_id = _validated_scanner_id(data)
    if data.get("enabled", True):
        _enforce_enabled_alert_cap(team, scanner_id)
    kwargs: dict[str, Any] = {
        "team_id": team.id,
        "scanner_id": scanner_id,
        "name": data.get("name") or "Untitled alert",
        "enabled": data.get("enabled", True),
        "created_by": user,
        "first_enabled_at": timezone.now(),
        "selection": {
            k: v for k, v in (data.get("selection") or {}).items() if k in ("verdict", "tags", "min_score", "max_score")
        },
    }
    if frequency == "on_breach":
        kwargs.update(
            kind=VisionAlertKind.METRIC,
            metric=config.get("metric", "count"),
            direction=config.get("direction", "above"),
            threshold=float(config.get("threshold", 1)),
            window_days=int(config.get("window_days", 1)),
        )
    else:
        kwargs.update(kind=VisionAlertKind.MATCH, threshold=None)
    alert = VisionAlertConfiguration.objects.for_team(team.id).create(**kwargs)

    _provision_alert_destinations(team, user, alert, data.get("delivery_config") or [])
    return render_alert_as_action(alert)


def _provision_alert_destinations(
    team: Team, user: User, alert: VisionAlertConfiguration, entries: list[dict[str, Any]]
) -> None:
    kinds = MATCH_EVENT_KINDS if alert.kind == VisionAlertKind.MATCH else METRIC_EVENT_KINDS
    for entry in entries:
        destination = _legacy_destination_data(entry)
        if destination is None:
            continue
        configs = [
            build_alert_destination_config(
                team=team,
                spec=EVENT_KIND_CONFIG[kind],
                alert_id=str(alert.id),
                alert_name=alert.name,
                data=destination,
                slack_context_elements=VISION_ALERT_SLACK_CONTEXT_ELEMENTS,
            )
            for kind in kinds
        ]
        create_alert_destination_hog_functions(
            configs,
            request=SimpleNamespace(user=user),
            alert_id=str(alert.id),
            allowed_event_ids=VISION_ALERT_EVENT_IDS,
        )


def _scout_destinations_from_legacy(data: dict[str, Any]) -> dict[str, Any]:
    destinations: dict[str, Any] = {}
    for entry in data.get("delivery_config") or []:
        if entry.get("type") == "slack" and "slack" not in destinations:
            channel = str(entry.get("channel") or "")
            channel_id, _, channel_name = channel.partition("|")
            destinations["slack"] = {
                "integration_id": entry.get("integration_id"),
                "channel_id": channel_id,
                "channel_name": channel_name or channel_id,
            }
        elif entry.get("type") == "webhook" and entry.get("url") and "webhook" not in destinations:
            destinations["webhook"] = {"url": entry["url"]}
    return destinations


def _create_scout(team: Team, user: User, data: dict[str, Any]) -> dict[str, Any]:
    scanner_id = _validated_scanner_id(data)
    name = data.get("name") or "digest"
    rrule = (data.get("trigger_config") or {}).get("rrule") or "FREQ=DAILY;BYHOUR=8;BYMINUTE=0"
    try:
        cron = rrule_to_cron(rrule)
    except ValueError as error:
        raise ValidationError({"trigger_config": str(error)})

    prompt_guide = (data.get("synthesis_config") or {}).get("prompt_guide")
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:34] or "digest"
    scout_name = f"signals-scout-{slug}"
    destinations = _scout_destinations_from_legacy(data)
    result = signals_facade.create_scout_for_source(
        team=team.parent_team or team,
        user=user,
        name=scout_name,
        description=prompt_guide or f'Replay Vision digest "{name}".',
        body=compose_digest_scout_body(
            str(scanner_id),
            selection=data.get("selection"),
            prompt_guide=prompt_guide,
            max_observations=data.get("max_observations"),
        ),
        files=[],
        config_options={
            "enabled": data.get("enabled", True),
            "run_cron_schedule": cron,
            **({"output_destinations": destinations} if destinations else {}),
        },
        request=SimpleNamespace(user=user),
        serializer_context={"project_id": team.project_id},
        source_product=SCOUT_SOURCE_PRODUCT,
        source_id=str(scanner_id),
    )
    created = resolve_entities(team, str(result.config.id))
    if not created:
        raise NotFound()
    return render_entity(created[0])


def update_action(team: Team, entries: list[tuple[str, Any]], data: dict[str, Any], user: User) -> dict[str, Any]:
    rendered = [_update_one(team, kind, entity, data, user) for kind, entity in entries]
    return rendered[0]


def _update_one(team: Team, kind: str, entity: Any, data: dict[str, Any], user: User) -> dict[str, Any]:
    if kind == "alert":
        config = data.get("alert_config") or {}
        frequency = config.get("frequency")
        if frequency is not None:
            wanted = VisionAlertKind.MATCH if frequency == "every_match" else VisionAlertKind.METRIC
            if wanted != entity.kind:
                # kind is immutable on an alert (the DB constraint pins match alerts stateless), so
                # accepting the field and ignoring it would report a change that never happened.
                raise ValidationError(
                    {"alert_config": "Cannot change an alert's frequency. Delete it and create a new one."}
                )
        if data.get("enabled") and not entity.enabled:
            _enforce_enabled_alert_cap(team, str(entity.scanner_id), exclude_id=str(entity.id))
        update_fields: list[str] = []
        for key in ("name", "selection"):
            if key in data:
                setattr(entity, key, data[key])
                update_fields.append(key)
        threshold_changed = False
        if config and entity.kind == VisionAlertKind.METRIC:
            for key in ("metric", "direction", "threshold", "window_days"):
                if key in config and config[key] != getattr(entity, key):
                    setattr(entity, key, config[key])
                    update_fields.append(key)
                    threshold_changed = True
        enabled_change = data["enabled"] if "enabled" in data and data["enabled"] != entity.enabled else None
        with transaction.atomic():
            # Lifecycle fields belong to the state machine: setting `enabled` directly would leave a
            # re-enabled alert still FIRING with its old failure count, and write no audit row.
            snapshot = entity.to_snapshot()
            # The two writes below are the fields their adjacent apply_outcome call transitions;
            # the state machine still decides state and failure counts.
            if enabled_change is True:
                entity.enabled = True  # nosemgrep: replay-vision-alert-state-direct-mutation
                update_fields.extend(apply_outcome(entity, apply_enable(snapshot), kind=VisionAlertEvent.Kind.ENABLE))
            elif enabled_change is False:
                entity.enabled = False  # nosemgrep: replay-vision-alert-state-direct-mutation
                update_fields.extend(apply_outcome(entity, apply_disable(snapshot), kind=VisionAlertEvent.Kind.DISABLE))
            elif threshold_changed:
                update_fields.extend(
                    apply_outcome(entity, apply_threshold_change(snapshot), kind=VisionAlertEvent.Kind.THRESHOLD_CHANGE)
                )
                entity.clear_next_check()
                update_fields.append("next_check_at")
            if enabled_change is not None:
                update_fields.append("enabled")
            if update_fields:
                entity.save(update_fields=[*set(update_fields), "updated_at"])
            if "delivery_config" in data:
                # Destinations are hog functions, not columns: without rebuilding them, a caller
                # who edits delivery_config gets a 200 while notifications keep going to the old
                # channel.
                soft_delete_all_alert_destinations(
                    team_id=team.id, alert_id=str(entity.id), allowed_event_ids=VISION_ALERT_EVENT_IDS
                )
                _provision_alert_destinations(team, user, entity, data.get("delivery_config") or [])
        return render_alert_as_action(entity)

    cron = None
    rrule = (data.get("trigger_config") or {}).get("rrule")
    if rrule:
        try:
            cron = rrule_to_cron(rrule)
        except ValueError as error:
            raise ValidationError({"trigger_config": str(error)})
    unsupported = sorted({"name", "selection", "synthesis_config", "mode", "scanner"} & set(data))
    if unsupported:
        # Better a clear refusal than a 200 that keeps the old values: a scout's name and prompt are
        # its skill, and editing a skill has its own authoring bar that this surface cannot clear.
        raise ValidationError(
            {
                unsupported[0]: f"Edit {', '.join(unsupported)} on the scout itself; this surface can change "
                "the schedule, enablement, and delivery targets."
            }
        )
    destinations = _scout_destinations_from_legacy(data) if "delivery_config" in data else None
    if not signals_facade.update_scout_for_source(
        (team.parent_team or team).id,
        SCOUT_SOURCE_PRODUCT,
        entity.config_id,
        enabled=data.get("enabled"),
        run_cron_schedule=cron,
        output_destinations=destinations,
    ):
        raise NotFound()
    refreshed = resolve_entities(team, entity.config_id)
    if not refreshed:
        raise NotFound()
    return render_entity(refreshed[0])


def destroy_action(team: Team, entries: list[tuple[str, Any]]) -> None:
    for kind, entity in entries:
        _destroy_one(team, kind, entity)


def _destroy_one(team: Team, kind: str, entity: Any) -> None:
    if kind == "alert":
        soft_delete_all_alert_destinations(
            team_id=team.id, alert_id=str(entity.id), allowed_event_ids=VISION_ALERT_EVENT_IDS
        )
        entity.delete()
        return
    if not signals_facade.delete_scout_for_source(
        team=team.parent_team or team, source_product=SCOUT_SOURCE_PRODUCT, config_id=entity.config_id
    ):
        raise NotFound()
