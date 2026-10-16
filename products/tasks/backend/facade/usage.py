from __future__ import annotations

from typing import TYPE_CHECKING

from products.tasks.backend.logic.services.code_usage_gate import usage_limit_response

if TYPE_CHECKING:
    from posthog.models import User


def task_run_usage_limited(user: User, team_id: int) -> bool:
    return usage_limit_response(user, team_id) is not None
