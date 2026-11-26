import datetime

import pytest

from products.warehouse_sources.sources.sdk.testing import RecordedRequest, ScriptedResponse, SourceDriver
from products.warehouse_sources.sources.torii._config import ToriiSourceConfig
from products.warehouse_sources.sources.torii.source import ToriiSource
from products.warehouse_sources.sources.torii.torii import ToriiResumeConfig

# Top-level endpoints that page with Torii's `nextCursor`, keyed to the response key of their rows.
_DATA_SELECTOR = {
    "Apps": "apps",
    "Users": "users",
    "Contracts": "contracts",
    "Transactions": "transactions",
    "ActionExecutions": "response",
    "Audit": "audit",
}


class TestToriiSourceResumeBehavior:
    """End-to-end pagination/resume behaviour of ``ToriiSource``, driven through ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(ToriiSource(), ToriiSourceConfig(api_key="test-key"))

    @pytest.mark.parametrize("endpoint", list(_DATA_SELECTOR))
    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self, endpoint: str) -> None:
        key = _DATA_SELECTOR[endpoint]

        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(json={key: [{"id": "1"}], "count": 1, "total": 3, "nextCursor": "cursor-1"}),
                ScriptedResponse(json={key: [{"id": "2"}], "count": 1, "total": 3, "nextCursor": "cursor-2"}),
                ScriptedResponse(json={key: [{"id": "3"}], "count": 1, "total": 3}),
            ],
        )

        assert result.params("cursor") == [None, "cursor-1", "cursor-2"]
        assert result.saved_states == [
            ToriiResumeConfig(cursor="cursor-1"),
            ToriiResumeConfig(cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "Apps",
            [ScriptedResponse(json={"apps": [{"id": "only"}]})],
            resume_state=ToriiResumeConfig(cursor="cursor-resumed"),
        )

        assert result.params("cursor") == ["cursor-resumed"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = self._driver().run("Apps", [ScriptedResponse(json={"apps": [{"id": "a"}]})])

        assert result.params("cursor") == [None]

    @pytest.mark.parametrize(
        "endpoint, path, key",
        [
            ("Roles", "/v1.0/roles", "roles"),
            ("Workflows", "/v1.0/workflows", "workflows"),
        ],
    )
    def test_single_page_endpoints_stop_after_one_page(self, endpoint: str, path: str, key: str) -> None:
        result = self._driver().run(
            endpoint,
            [ScriptedResponse(json={key: [{"id": 1, "name": "First"}], "nextCursor": "ignored"})],
        )

        assert result.raised is None
        assert result.paths == [path]
        assert [row["id"] for row in result.rows] == [1]


def _audit_event(**overrides: object) -> dict:
    return {
        "performedBy": 1000,
        "performedByFirstName": "Ada",
        "performedByLastName": "Example",
        "performedByEmail": "ada@example.com",
        "idTargetOrg": 42,
        "creationTime": "2026-03-10T05:00:00.000Z",
        "type": "update_contract",
        "requestDetails": {"path": "/api/orgs/42/contracts/7", "method": "put", "remoteAddress": "192.0.2.1"},
        "properties": {"idContract": 7, "status": "active"},
        **overrides,
    }


class TestToriiAudit:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(ToriiSource(), ToriiSourceConfig(api_key="test-key"))

    @pytest.mark.parametrize(
        "inputs, expected_start, expected_sort_mode",
        [
            ({}, None, None),
            ({"incremental_field": "creationTime"}, None, "asc"),
            (
                {
                    "incremental_field": "creationTime",
                    "db_incremental_field_last_value": datetime.datetime(2026, 3, 10, 5, 0, tzinfo=datetime.UTC),
                },
                "2026-03-09",
                "asc",
            ),
            (
                {
                    "incremental_field": "creationTime",
                    "db_incremental_field_last_value": datetime.datetime(2026, 3, 1, 0, 0, tzinfo=datetime.UTC),
                },
                "2026-02-28",
                "asc",
            ),
            (
                {
                    "should_use_incremental_field": False,
                    "incremental_field": "creationTime",
                    "db_incremental_field_last_value": datetime.datetime(2026, 3, 10, 5, 0, tzinfo=datetime.UTC),
                },
                None,
                None,
            ),
        ],
    )
    def test_request_shape_for_full_refresh_and_incremental(
        self, inputs: dict, expected_start: str | None, expected_sort_mode: str | None
    ) -> None:
        result = self._driver().run("Audit", [ScriptedResponse(json={"audit": [_audit_event()]})], **inputs)

        assert result.raised is None
        assert result.paths == ["/v1.0/audit"]
        assert result.params("sort") == ["asc"]
        assert result.params("startTime") == [expected_start]
        assert result.response is not None
        assert result.response.sort_mode == expected_sort_mode

    @pytest.mark.parametrize(
        "other, same_id",
        [
            (_audit_event(), True),
            (_audit_event(performedByFirstName="Renamed", performedByEmail="renamed@example.com"), True),
            (_audit_event(properties={"status": "active", "idContract": 7}), True),
            (_audit_event(properties={"idContract": 8, "status": "active"}), False),
            (_audit_event(creationTime="2026-03-10T05:00:00.001Z"), False),
            (_audit_event(type="delete_contract"), False),
            (_audit_event(performedBy=-1), False),
            (_audit_event(requestDetails=None), False),
        ],
    )
    def test_synthetic_id_is_stable_for_the_same_event(self, other: dict, same_id: bool) -> None:
        result = self._driver().run("Audit", [ScriptedResponse(json={"audit": [_audit_event(), other]})])

        assert result.raised is None
        first, second = result.rows
        assert len(first["id"]) == 64
        assert (first["id"] == second["id"]) is same_id


def _app_users_script(request: RecordedRequest) -> ScriptedResponse:
    if request.path == "/v1.0/apps":
        if request.param("cursor") is None:
            return ScriptedResponse(json={"apps": [{"id": 10}, {"id": 20}], "nextCursor": "apps-2"})
        return ScriptedResponse(json={"apps": [{"id": 30}]})
    if request.path == "/v1.0/apps/10/users":
        if request.param("cursor") is None:
            return ScriptedResponse(json={"users": [{"idUser": 1, "idAppAccount": 5}], "nextCursor": "u-2"})
        return ScriptedResponse(json={"users": [{"idUser": 2, "idAppAccount": 5}]})
    if request.path == "/v1.0/apps/20/users":
        return ScriptedResponse(status=404, json={"error": "not found"})
    if request.path == "/v1.0/apps/30/users":
        return ScriptedResponse(json={"users": [{"idUser": 1, "idAppAccount": 7}]})
    raise AssertionError(f"unexpected request {request.url}")


class TestToriiAppUsers:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(ToriiSource(), ToriiSourceConfig(api_key="test-key"))

    def test_walks_every_app_and_every_user_page(self) -> None:
        result = self._driver().run("AppUsers", _app_users_script)

        assert result.raised is None
        assert [(row["idApp"], row["idUser"], row["idAppAccount"]) for row in result.rows] == [
            (10, 1, 5),
            (10, 2, 5),
            (30, 1, 7),
        ]
        assert result.paths == [
            "/v1.0/apps",
            "/v1.0/apps/10/users",
            "/v1.0/apps/10/users",
            "/v1.0/apps/20/users",
            "/v1.0/apps",
            "/v1.0/apps/30/users",
        ]
        assert all(state.fanout_state and state.cursor is None for state in result.saved_states)

    def test_resume_skips_the_apps_a_previous_attempt_finished(self) -> None:
        first = self._driver().run("AppUsers", _app_users_script)
        after_first_app = next(
            state for state in first.saved_states if state.fanout_state and state.fanout_state.get("completed")
        )

        result = self._driver().run("AppUsers", _app_users_script, resume_state=after_first_app)

        assert result.raised is None
        assert "/v1.0/apps/10/users" not in result.paths
        assert {row["idApp"] for row in result.rows} == {30}


def _metadata_body(predefined: list[dict], custom: list[dict]) -> dict:
    return {"predefinedFields": predefined, "customFields": custom}


class TestToriiFieldsMetadata:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(ToriiSource(), ToriiSourceConfig(api_key="test-key"))

    def test_tags_each_field_with_its_entity_and_kind(self) -> None:
        result = self._driver().run(
            "FieldsMetadata",
            [
                ScriptedResponse(json=_metadata_body([{"systemKey": "name"}], [{"systemKey": "c_1", "idField": 1}])),
                ScriptedResponse(json=_metadata_body([], [])),
                ScriptedResponse(json={"predefinedFields": [{"systemKey": "status"}], "customFields": None}),
                ScriptedResponse(json=_metadata_body([{"systemKey": "amount"}], [])),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/v1.0/apps/metadata",
            "/v1.0/users/metadata",
            "/v1.0/contracts/metadata",
            "/v1.0/transactions/metadata",
        ]
        assert [(row["entity"], row["systemKey"], row["isCustom"]) for row in result.rows] == [
            ("apps", "name", False),
            ("apps", "c_1", True),
            ("contracts", "status", False),
            ("transactions", "amount", False),
        ]

    def test_non_object_body_fails_the_run(self) -> None:
        result = self._driver().run("FieldsMetadata", [ScriptedResponse(json=["unexpected"])])

        assert isinstance(result.raised, ValueError)
