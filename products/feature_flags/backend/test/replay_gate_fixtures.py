"""Builders for the session replay recording gate a team stores on `Team`.

The shape these emit is the contract the production matchers key off, so every suite that needs a
gated team builds it here rather than keeping its own copy to drift.
"""

from typing import Any

from posthog.models import Team


def trigger_groups(*conditions: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 2,
        "groups": [
            {"id": f"group-{index}", "sampleRate": 1, "conditions": {"matchType": "any", **condition}}
            for index, condition in enumerate(conditions)
        ],
    }


def set_trigger_groups(team: Team, *conditions: dict[str, Any]) -> None:
    team.session_recording_trigger_groups = trigger_groups(*conditions)
    team.save()


def set_linked_flag(team: Team, linked_flag: dict[str, Any] | None) -> None:
    team.session_recording_linked_flag = linked_flag
    team.save()
