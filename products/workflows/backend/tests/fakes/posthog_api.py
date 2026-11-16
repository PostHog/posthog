import re
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from unittest.mock import patch

import responses
import posthoganalytics

from posthog.dataclasses import frozen

from products.workflows.backend.facade.sandbox_email import SANDBOX_SENDER_ADOPTION_FLAG

HOST = "https://posthog.example.com"


@frozen
class Exposure:
    flag: str
    response: Any
    groups: dict[str, str]


def boolean_flag() -> dict[str, Any]:
    return _flag({"groups": [{"properties": [], "rollout_percentage": 100}]})


def variant_flag(variant: str, *, first_workflow_after: str | None = None) -> dict[str, Any]:
    properties = (
        [
            {
                "key": "workflows_first_created_at",
                "type": "group",
                "group_type_index": 0,
                "operator": "is_date_after",
                "value": first_workflow_after,
            }
        ]
        if first_workflow_after
        else []
    )
    return _flag(
        {
            "groups": [{"properties": properties, "rollout_percentage": 100, "variant": variant}],
            "multivariate": {
                "variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ]
            },
        }
    )


def _flag(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": 1,
        "key": SANDBOX_SENDER_ADOPTION_FLAG,
        "active": True,
        "filters": {"aggregation_group_type_index": 0, **filters},
    }


class FakePostHogApi:
    """PostHog's flag definition and event endpoints, served to a real SDK client so the flag is
    evaluated the way production evaluates it and the exposure events it sends can be read back."""

    def __init__(self, *flags: dict[str, Any]) -> None:
        self._flags = list(flags)
        self._events: list[dict[str, Any]] = []

    @contextmanager
    def installed(self) -> Iterator["FakePostHogApi"]:
        client = posthoganalytics.Client(
            "phc_fake", host=HOST, personal_api_key="phx_fake", sync_mode=True, enable_local_evaluation=False
        )
        with (
            responses.RequestsMock(assert_all_requests_are_fired=False) as calls,
            patch("posthoganalytics.default_client", client),
            patch("posthoganalytics.disabled", False),
        ):
            calls.get(
                re.compile(re.escape(HOST) + r"/flags/definitions"),
                json={"flags": self._flags, "group_type_mapping": {"0": "organization"}, "cohorts": {}},
            )
            calls.post(re.compile(re.escape(HOST) + r"/flags/\?"), json={"flags": {}})
            calls.post(re.compile(re.escape(HOST) + r"/batch/"), json={"status": 1})
            try:
                yield self
            finally:
                client.shutdown()
                self._events = [
                    event
                    for call in calls.calls
                    if call.request.url and "/batch/" in call.request.url and call.request.body
                    for event in json.loads(call.request.body)["batch"]
                ]

    def exposures(self) -> list[Exposure]:
        return [
            Exposure(
                flag=event["properties"]["$feature_flag"],
                response=event["properties"]["$feature_flag_response"],
                groups=event["properties"].get("$groups", {}),
            )
            for event in self._events
            if event["event"] == "$feature_flag_called"
        ]
