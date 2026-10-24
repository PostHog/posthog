import json

from django.core.management.base import BaseCommand
from django.db import connection

from posthog.temporal.oauth import get_array_app, get_wizard_app

from products.feature_flags.backend.models.feature_flag import FeatureFlag

SETUP_FIX = "python manage.py setup_background_agents"
WIZARD_FIX = "bin/ensure-local-setup"


def check_database() -> dict[str, str]:
    try:
        connection.ensure_connection()
    except Exception as error:
        return _result("db.connection", "error", f"cannot connect: {type(error).__name__}", "hogli start")
    return _result("db.connection", "ok", "connected")


def check_array_oauth_app() -> dict[str, str]:
    try:
        get_array_app()
    except RuntimeError:
        return _result("db.array_oauth_app", "error", "sandbox OAuth app missing", SETUP_FIX)
    return _result("db.array_oauth_app", "ok", "present")


def check_wizard_oauth_app() -> dict[str, str]:
    try:
        get_wizard_app()
    except RuntimeError:
        return _result("db.wizard_oauth_app", "warn", "missing, wizard cloud runs return 404", WIZARD_FIX)
    return _result("db.wizard_oauth_app", "ok", "present")


def check_tasks_flag() -> dict[str, str]:
    active_count = FeatureFlag.objects.filter(key="tasks", active=True, deleted=False).count()
    if active_count == 0:
        return _result("db.tasks_flag", "warn", "no team has the tasks flag active", SETUP_FIX)
    return _result("db.tasks_flag", "ok", f"active for {active_count} team(s)")


def _result(check_id: str, status: str, summary: str, fix: str | None = None) -> dict[str, str]:
    result = {"id": check_id, "status": status, "summary": summary}
    if fix is not None:
        result["fix"] = fix
    return result


class Command(BaseCommand):
    help = "Read-only checks of the database state local task runs need. Prints JSON."
    requires_system_checks: list[str] = []

    def handle(self, *args, **options):
        database = check_database()
        results = [database]
        if database["status"] == "ok":
            results += [check_array_oauth_app(), check_wizard_oauth_app(), check_tasks_flag()]
        self.stdout.write(json.dumps(results))
