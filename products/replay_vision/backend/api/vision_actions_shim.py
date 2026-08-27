"""Serve the legacy vision-actions API surface from the new alerts and scouts systems.

Once an organization is on the `replay-vision-alerts` flag, the legacy endpoints stop touching
`VisionAction` rows: creates become alerts or scouts, reads synthesize legacy-shaped responses
from the new entities, and updates and deletes resolve ids across all three id spaces (new alert
uuids, scout config ids, and migrated legacy row ids via their `migrated_to` stamps). Existing
MCP and agent callers keep their contract without knowing anything moved.
"""

import re
from types import SimpleNamespace
from typing import Any, cast

from django.utils import timezone

from rest_framework.exceptions import NotFound, ValidationError

from posthog.models import Team, User

from products.alerts.backend.destination_configs import AlertDestinationData, DestinationType
from products.alerts.backend.destinations import owned_alert_destinations_qs
from products.alerts.backend.facade.api import (
    build_alert_destination_config,
    create_alert_destination_hog_functions,
    soft_delete_all_alert_destinations,
)
from products.replay_vision.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    MATCH_EVENT_KINDS,
    METRIC_EVENT_KINDS,
    VISION_ALERT_EVENT_IDS,
    VISION_ALERT_SLACK_CONTEXT_ELEMENTS,
)
from products.replay_vision.backend.models.vision_action import ActionMode, VisionAction
from products.replay_vision.backend.models.vision_alert import VisionAlertConfiguration, VisionAlertKind
from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT
from products.signals.backend.facade import api as signals_facade
from products.signals.backend.facade.api import ScoutSummary

_CRON_DAY_TO_RRULE = {"0": "SU", "1": "MO", "2": "TU", "3": "WE", "4": "TH", "5": "FR", "6": "SA", "7": "SU"}
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
        return f"{minute} {hour} * * *"
    if freq == "WEEKLY":
        days = parts.get("BYDAY")
        cron_days = ",".join(str(_DAY_TO_CRON[d]) for d in days.split(",")) if days else "1"
        return f"{minute} {hour} * * {cron_days}"
    raise ValueError(f"Unsupported rrule: {rrule}")


def compose_scout_body(
    name: str, scanner_name: str, selection: dict[str, Any], synthesis_config: dict[str, Any]
) -> str:
    lines = [
        f'You are producing the recurring digest previously configured as "{name}" for the scanner "{scanner_name}".',
        "",
        "Summarize the scanner's new observations since the previous report.",
    ]
    filters: list[str] = []
    if selection.get("verdict"):
        verdicts = selection["verdict"] if isinstance(selection["verdict"], list) else [selection["verdict"]]
        filters.append(f"verdict in {verdicts}")
    if selection.get("tags"):
        filters.append(f"tags any of {selection['tags']}")
    if selection.get("min_score") is not None:
        filters.append(f"score >= {selection['min_score']}")
    if selection.get("max_score") is not None:
        filters.append(f"score <= {selection['max_score']}")
    if filters:
        lines += ["", "Only include observations matching: " + "; ".join(filters) + "."]
    guide = synthesis_config.get("prompt_guide")
    if guide:
        lines += ["", "Follow this guidance from the digest's author:", "", str(guide)]
    return "\n".join(lines)


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


def _delivery_config_for_alert(alert: VisionAlertConfiguration) -> list[dict[str, Any]]:
    """Rebuild the legacy delivery target list from the alert's destination hog functions."""
    targets: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    hog_functions = owned_alert_destinations_qs(
        team_id=alert.team_id, alert_ids=[str(alert.id)], allowed_event_ids=VISION_ALERT_EVENT_IDS
    ).filter(enabled=True)
    for hog_function in hog_functions:
        inputs = hog_function.inputs or {}
        template_id = hog_function.template_id or ""
        if "slack" in template_id:
            channel = (inputs.get("channel") or {}).get("value")
            integration = (inputs.get("slack_workspace") or {}).get("value")
            key = ("slack", integration, channel)
            if channel and key not in seen:
                seen.add(key)
                targets.append({"type": "slack", "integration_id": integration, "channel": channel})
        else:
            url = (inputs.get("url") or {}).get("value")
            key = ("webhook", url, None)
            if url and key not in seen:
                seen.add(key)
                targets.append({"type": "webhook", "url": url})
    return targets


def _scout_delivery_config(summary: ScoutSummary) -> list[dict[str, Any]]:
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
        targets.append({"type": "webhook", "url": webhook["url"]})
    return targets


def render_alert_as_action(alert: VisionAlertConfiguration) -> dict[str, Any]:
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
        "delivery_config": _delivery_config_for_alert(alert),
        "next_run_at": alert.next_check_at.isoformat() if alert.next_check_at else None,
        "last_run_at": alert.last_checked_at.isoformat() if alert.last_checked_at else None,
        "created_at": alert.created_at.isoformat(),
        "created_by": alert.created_by_id,
        "updated_at": alert.updated_at.isoformat(),
    }


def render_scout_as_action(summary: ScoutSummary) -> dict[str, Any]:
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
        "delivery_config": _scout_delivery_config(summary),
        "next_run_at": None,
        "last_run_at": summary.last_run_at.isoformat() if summary.last_run_at else None,
        "created_at": summary.created_at.isoformat() if summary.created_at else None,
        "created_by": summary.created_by_id,
        "updated_at": None,
    }


def list_actions(team: Team, scanner_ids: list[str] | None = None) -> list[dict[str, Any]]:
    alerts = VisionAlertConfiguration.objects.for_team(team.id).select_related("scanner").order_by("created_at")
    if scanner_ids:
        alerts = alerts.filter(scanner_id__in=scanner_ids)
    scouts = signals_facade.list_scouts_for_source(
        (team.parent_team or team).id, SCOUT_SOURCE_PRODUCT, source_ids=scanner_ids
    )
    return [render_alert_as_action(alert) for alert in alerts] + [render_scout_as_action(s) for s in scouts]


def _resolve(team: Team, pk: str) -> tuple[str, Any] | None:
    """Resolve an id from any of the three id spaces to ('alert', obj) or ('scout', summary)."""
    alert = VisionAlertConfiguration.objects.for_team(team.id).filter(id=pk).first()
    if alert is not None:
        return ("alert", alert)
    scouts = {
        s.config_id: s
        for s in signals_facade.list_scouts_for_source((team.parent_team or team).id, SCOUT_SOURCE_PRODUCT)
    }
    if pk in scouts:
        return ("scout", scouts[pk])
    legacy = VisionAction.objects.for_team(team.id).filter(id=pk).first()
    if legacy is not None:
        stamps = (legacy.alert_config or {}) if legacy.mode == ActionMode.ALERT else (legacy.synthesis_config or {})
        migrated = stamps.get("migrated_to")
        if isinstance(migrated, list) and migrated:
            migrated = migrated[0]
        if migrated:
            return _resolve(team, str(migrated)) or _resolve_scout_by_name(team, str(migrated))
    return None


def _resolve_scout_by_name(team: Team, name: str) -> tuple[str, ScoutSummary] | None:
    for summary in signals_facade.list_scouts_for_source((team.parent_team or team).id, SCOUT_SOURCE_PRODUCT):
        if summary.skill_name == name:
            return ("scout", summary)
    return None


def retrieve_action(team: Team, pk: str) -> dict[str, Any]:
    resolved = _resolve(team, pk)
    if resolved is None:
        raise NotFound()
    kind, entity = resolved
    return render_alert_as_action(entity) if kind == "alert" else render_scout_as_action(entity)


def create_action(team: Team, user: User, data: dict[str, Any]) -> dict[str, Any]:
    mode = data.get("mode", ActionMode.GROUP_SUMMARY)
    if mode == ActionMode.ALERT:
        return _create_alert(team, user, data)
    if mode == ActionMode.GROUP_SUMMARY:
        return _create_scout(team, user, data)
    raise ValidationError({"mode": f"Unsupported mode {mode!r}."})


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


def _create_alert(team: Team, user: User, data: dict[str, Any]) -> dict[str, Any]:
    config = data.get("alert_config") or {}
    frequency = config.get("frequency", "every_match")
    scanner_id = data.get("scanner") or data.get("scanner_id")
    if not scanner_id:
        raise ValidationError({"scanner": "This field is required."})
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

    kinds = MATCH_EVENT_KINDS if alert.kind == VisionAlertKind.MATCH else METRIC_EVENT_KINDS
    for entry in data.get("delivery_config") or []:
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
    return render_alert_as_action(alert)


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
    scanner_id = data.get("scanner") or data.get("scanner_id")
    if not scanner_id:
        raise ValidationError({"scanner": "This field is required."})
    name = data.get("name") or "digest"
    rrule = (data.get("trigger_config") or {}).get("rrule") or "FREQ=DAILY;BYHOUR=8;BYMINUTE=0"
    try:
        cron = rrule_to_cron(rrule)
    except ValueError as error:
        raise ValidationError({"trigger_config": str(error)})

    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:34] or "digest"
    scout_name = f"signals-scout-{slug}"
    destinations = _scout_destinations_from_legacy(data)
    result = signals_facade.create_scout_for_source(
        team=team.parent_team or team,
        user=user,
        name=scout_name,
        description=f'Replay Vision digest "{name}".',
        body=compose_scout_body(name, str(scanner_id), data.get("selection") or {}, data.get("synthesis_config") or {}),
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
    return retrieve_action(team, str(result.config.id))


def update_action(team: Team, pk: str, data: dict[str, Any]) -> dict[str, Any]:
    resolved = _resolve(team, pk)
    if resolved is None:
        raise NotFound()
    kind, entity = resolved
    if kind == "alert":
        update_fields: list[str] = []
        for source_key, target_key in (("name", "name"), ("enabled", "enabled"), ("selection", "selection")):
            if source_key in data:
                setattr(entity, target_key, data[source_key])
                update_fields.append(target_key)
        config = data.get("alert_config")
        if config and entity.kind == VisionAlertKind.METRIC:
            for key in ("metric", "direction", "threshold", "window_days"):
                if key in config:
                    setattr(entity, key, config[key])
                    update_fields.append(key)
        if update_fields:
            entity.save(update_fields=[*update_fields, "updated_at"])
        return render_alert_as_action(entity)

    cron = None
    rrule = (data.get("trigger_config") or {}).get("rrule")
    if rrule:
        try:
            cron = rrule_to_cron(rrule)
        except ValueError as error:
            raise ValidationError({"trigger_config": str(error)})
    destinations = _scout_destinations_from_legacy(data) if "delivery_config" in data else None
    signals_facade.update_scout_for_source(
        (team.parent_team or team).id,
        SCOUT_SOURCE_PRODUCT,
        entity.config_id,
        enabled=data.get("enabled"),
        run_cron_schedule=cron,
        output_destinations=destinations,
    )
    return retrieve_action(team, entity.config_id)


def destroy_action(team: Team, pk: str) -> None:
    resolved = _resolve(team, pk)
    if resolved is None:
        raise NotFound()
    kind, entity = resolved
    if kind == "alert":
        soft_delete_all_alert_destinations(
            team_id=team.id, alert_id=str(entity.id), allowed_event_ids=VISION_ALERT_EVENT_IDS
        )
        entity.delete()
        return
    signals_facade.delete_scout_for_source(
        team=team.parent_team or team, source_product=SCOUT_SOURCE_PRODUCT, config_id=entity.config_id
    )
