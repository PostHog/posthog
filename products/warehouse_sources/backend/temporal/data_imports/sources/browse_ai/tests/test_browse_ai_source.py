from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import Mock

import requests_mock

from posthog.cdp.validation import compile_hog

from products.warehouse_sources.backend.temporal.data_imports.sources.browse_ai.settings import BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.browse_ai.source import BrowseAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.browseai import (
    BrowseAISourceConfig,
)

from common.hogvm.python.execute import execute_bytecode

ROBOT = "00000000-0000-4000-8000-000000000001"
SECOND_ROBOT = "00000000-0000-4000-8000-000000000002"
HOOK = "00000000-0000-4000-8000-000000000003"
CALLBACK = "https://example.com/webhook/warehouse"


def test_invalid_schema_is_rejected_without_http() -> None:
    source = BrowseAISource()
    config = BrowseAISourceConfig(api_key="fake-key")
    assert source.validate_credentials(config, 1, "missing") == (False, "Unknown Browse AI schema: missing")
    with pytest.raises(ValueError, match="Unknown Browse AI schema"):
        source.source_for_pipeline(config, Mock(), Mock(schema_name="missing"))


def test_webhooks_create_idempotently_across_robots_and_delete_only_this_callback() -> None:
    source = BrowseAISource()
    config = BrowseAISourceConfig(api_key="fake-key")
    hooks: dict[str, list[dict[str, Any]]] = {ROBOT: [], SECOND_ROBOT: []}
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/robots", json={"robots": {"items": [{"id": ROBOT}, {"id": SECOND_ROBOT}]}})
        for robot in hooks:
            path = f"{BASE_URL}/robots/{robot}/webhooks"

            def list_hooks(request: Any, context: Any, robot_id: str = robot) -> dict[str, Any]:
                return {"webhooks": {"items": hooks[robot_id]}}

            def create_hook(request: Any, context: Any, robot_id: str = robot) -> dict[str, Any]:
                payload = request.json()
                hooks[robot_id].append({"id": HOOK, "url": payload["hookUrl"], "webhookEvent": payload["eventType"]})
                return {"result": hooks[robot_id][-1]}

            http.get(path, json=list_hooks)
            http.post(path, json=create_hook)
            http.delete(f"{path}/{HOOK}", status_code=204)

        created = source.create_webhook(config, CALLBACK, 1)
        assert created.success
        token = created.extra_inputs["webhook_token"]
        assert len(token) >= 32
        assert all(parse_qs(urlsplit(items[0]["url"]).query)["token"] == [token] for items in hooks.values())
        again = source.create_webhook(config, CALLBACK, 1)
        assert again.extra_inputs == created.extra_inputs
        assert len([request for request in http.request_history if request.method == "POST"]) == 2
        info = source.get_external_webhook_info(config, CALLBACK, 1)
        assert info.exists and info.status == "active"
        hooks[ROBOT].append(
            {"id": "leave-alone", "url": "https://example.com/another-webhook", "webhookEvent": "taskFinished"}
        )
        assert source.delete_webhook(config, CALLBACK, 1).success
        deletes = [request.url for request in http.request_history if request.method == "DELETE"]
        assert len(deletes) == 2
        assert all(url.endswith(HOOK) for url in deletes)


@pytest.mark.parametrize("robot_ids", [[], [ROBOT]])
def test_webhook_status_reports_missing_or_incomplete_subscriptions(robot_ids: list[str]) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/robots", json={"robots": {"items": [{"id": value} for value in robot_ids]}})
        http.get(f"{BASE_URL}/robots/{ROBOT}/webhooks", json={"webhooks": {"items": []}})
        source = BrowseAISource()
        config = BrowseAISourceConfig(api_key="fake-key")
        info = source.get_external_webhook_info(config, CALLBACK, 1)
        assert not info.exists
        assert info.status == "incomplete"
        if not robot_ids:
            result = source.create_webhook(config, CALLBACK, 1)
            assert not result.success
            assert result.error == "Create a Browse AI robot before enabling webhooks."


@pytest.fixture(scope="module")
def webhook_bytecode() -> list[Any]:
    template = BrowseAISource().webhook_template
    return compile_hog(template.code, template.type)


@pytest.mark.parametrize(
    "method,token,event,task,mapped,status,deliver",
    [
        ("POST", "fake-token", "task.finishedSuccessfully", {"id": "t1", "robotId": ROBOT}, True, None, True),
        ("POST", "fake-token", "task.finishedWithError", {"id": "t1", "robotId": ROBOT}, True, None, True),
        ("POST", "wrong", "task.finishedSuccessfully", {"id": "t1", "robotId": ROBOT}, True, 401, False),
        ("POST", None, "task.finishedSuccessfully", {"id": "t1", "robotId": ROBOT}, True, 401, False),
        ("GET", "fake-token", "task.finishedSuccessfully", {"id": "t1", "robotId": ROBOT}, True, 405, False),
        ("POST", "fake-token", "unknown", {"id": "t1", "robotId": ROBOT}, True, 200, False),
        ("POST", "fake-token", "task.finishedSuccessfully", {}, True, 400, False),
        ("POST", "fake-token", "task.finishedSuccessfully", {"id": "t1", "robotId": ROBOT}, False, None, False),
    ],
)
def test_webhook_authentication_and_routing(
    webhook_bytecode: list[Any],
    method: str,
    token: str | None,
    event: str,
    task: dict[str, Any],
    mapped: bool,
    status: int | None,
    deliver: bool,
) -> None:
    produce = Mock()
    result = execute_bytecode(
        webhook_bytecode,
        {
            "request": {"method": method, "query": {"token": token}, "body": {"event": event, "task": task}},
            "inputs": {
                "webhook_token": "fake-token",
                "schema_mapping": {BrowseAISource().webhook_resource_map["tasks"]: "schema-1"} if mapped else {},
            },
        },
        functions={"produceToWarehouseWebhooks": produce},
    )
    if status:
        assert result.result["httpResponse"]["status"] == status
    if deliver:
        produce.assert_called_once_with({"task": task}, "schema-1")
    else:
        produce.assert_not_called()


def test_conflicting_webhook_tokens_fail_without_creating_more_hooks() -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/robots", json={"robots": {"items": [{"id": ROBOT}]}})
        http.get(
            f"{BASE_URL}/robots/{ROBOT}/webhooks",
            json={
                "webhooks": {
                    "items": [
                        {"id": str(index), "url": f"{CALLBACK}?token=fake-{index}", "webhookEvent": "taskFinished"}
                        for index in range(2)
                    ]
                }
            },
        )
        result = BrowseAISource().create_webhook(BrowseAISourceConfig(api_key="fake-key"), CALLBACK, 1)
        assert not result.success
        assert result.error == "Delete the existing Browse AI webhooks and reconnect them."
        assert all(request.method == "GET" for request in http.request_history)
