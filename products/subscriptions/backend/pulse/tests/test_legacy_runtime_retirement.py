from typing import cast

from celery.schedules import crontab

from posthog.management.commands.start_temporal_worker import WORKFLOWS_DICT
from posthog.tasks.scheduled import setup_periodic_tasks

from products.pulse.backend.routes import register_routes


class _ProjectsRouter:
    def __init__(self) -> None:
        self.registered: list[str] = []

    def register(self, prefix: str, *args: object, **kwargs: object) -> None:
        self.registered.append(prefix)


class _RouterRegistry:
    def __init__(self) -> None:
        self.projects = _ProjectsRouter()


class _ScheduleSender:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.registrations: list[tuple[object, object, str | None, dict[str, object]]] = []

    def add_periodic_task(self, schedule: object, signature: object, name: str | None = None, **kwargs: object) -> None:
        self.registrations.append((schedule, signature, name, kwargs))
        if name is not None:
            self.names.append(name)


def test_legacy_pulse_routes_are_not_registered() -> None:
    routers = _RouterRegistry()

    register_routes(routers)  # type: ignore[arg-type]

    assert routers.projects.registered == []


def test_legacy_pulse_workflows_are_not_registered() -> None:
    workflows = [workflow for worker_workflows in WORKFLOWS_DICT.values() for workflow in worker_workflows]

    assert all(workflow.__module__ != "products.pulse.backend.temporal.workflow" for workflow in workflows)


def test_legacy_pulse_reaper_is_not_scheduled() -> None:
    sender = _ScheduleSender()

    setup_periodic_tasks(sender)

    assert "mark stale pulse briefs failed" not in sender.names


def test_proactive_pulse_reaper_is_scheduled_every_five_minutes_with_matching_expiry() -> None:
    sender = _ScheduleSender()

    setup_periodic_tasks(sender)

    schedule, _, _, kwargs = next(
        registration
        for registration in sender.registrations
        if registration[2] == "reconcile proactive subscription Pulse runs"
    )
    assert cast(crontab, schedule).minute == set(range(0, 60, 5))
    assert kwargs["expires"] == 5 * 60
