from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotlercrm import (
    SpotlerCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.source import SpotlerCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.spotlercrm import (
    SpotlerCRMPaginator,
    SpotlerCRMResumeConfig,
    get_endpoint_permissions,
    validate_credentials,
)


def _page_body(records: list[dict[str, Any]], has_more: bool | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"url": "/accounts", "object_type": "list"}
    if has_more is not None:
        metadata["has_more"] = has_more
    return {"metadata": metadata, "list": [{"metadata": {}, "record": record} for record in records]}


def _page(records: list[dict[str, Any]], has_more: bool | None = None) -> ScriptedResponse:
    return ScriptedResponse(json=_page_body(records, has_more))


class TestSpotlerCRMPaginator:
    def _json_response(self, body: dict[str, Any]) -> MagicMock:
        response = MagicMock()
        response.json.return_value = body
        return response

    def test_no_resume_state_on_terminal_page(self) -> None:
        paginator = SpotlerCRMPaginator()
        paginator.update_state(self._json_response(_page_body([], has_more=False)), [])

        assert paginator.get_resume_state() is None


class TestSpotlerCRMSourceBehavior:
    def _drive(
        self, endpoint: str, script: list[ScriptedResponse], resume_state: SpotlerCRMResumeConfig | None = None
    ) -> DriveResult:
        config = SpotlerCRMSourceConfig(access_token="test-token")
        return SourceDriver(SpotlerCRMSource(), config).run(endpoint, script, resume_state=resume_state)

    @pytest.mark.parametrize(
        ("endpoint", "expected_path"),
        [
            ("Accounts", "/accounts"),
            ("CampaignDetails", "/campaigndetails"),
            ("CampaignStages", "/campaignstages"),
        ],
    )
    def test_fresh_run_pages_forward_and_checkpoints_after_each_page(self, endpoint: str, expected_path: str) -> None:
        result = self._drive(
            endpoint,
            [
                _page([{"id": 1}], has_more=True),
                _page([{"id": 2}], has_more=True),
                _page([{"id": 3}], has_more=False),
            ],
        )

        assert result.paths == [expected_path] * 3
        assert result.params("page") == ["1", "2", "3"]
        assert result.params("limit") == ["100", "100", "100"]
        assert result.items == [[{"id": 1}], [{"id": 2}], [{"id": 3}]]
        assert result.saved_states == [
            SpotlerCRMResumeConfig(next_page=2),
            SpotlerCRMResumeConfig(next_page=3),
        ]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._drive(
            "Contacts",
            [_page([{"id": 42}], has_more=False)],
            resume_state=SpotlerCRMResumeConfig(next_page=5),
        )

        assert result.params("page") == ["5"]


class TestSpotlerCRMCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (402, False),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            valid, error = validate_credentials("test-token")

        assert valid is expected_valid
        assert (error is None) is expected_valid

    @pytest.mark.parametrize(
        ("status_code", "expects_reason"),
        [
            (200, False),
            (402, True),
            (403, True),
            (404, True),
            (500, False),  # transient failures must not read as missing permissions
        ],
    )
    def test_get_endpoint_permissions_status_mapping(self, status_code: int, expects_reason: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            permissions = get_endpoint_permissions("test-token", ["Cases"])

        assert (permissions["Cases"] is not None) is expects_reason

    def test_get_endpoint_permissions_treats_network_errors_as_reachable(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            permissions = get_endpoint_permissions("test-token", ["Accounts"])

        assert permissions["Accounts"] is None
