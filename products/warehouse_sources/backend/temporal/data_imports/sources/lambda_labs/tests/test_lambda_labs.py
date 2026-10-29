from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lambdalabs import (
    LambdaLabsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.lambda_labs import (
    LambdaLabsResumeConfig,
    _format_iso8601,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.source import LambdaLabsSource


def _driver() -> SourceDriver:
    return SourceDriver(LambdaLabsSource(), LambdaLabsSourceConfig(api_key="secret_key"))


class TestExtractRecords:
    @pytest.mark.parametrize(
        ("endpoint", "body", "expected"),
        [
            (
                "instances",
                {"data": [{"id": "i-1"}, {"id": "i-2"}]},
                [{"id": "i-1"}, {"id": "i-2"}],
            ),
            (
                # A live JupyterLab access token (and the URL embedding it) must be stripped so it
                # never lands in the warehouse where a project member could retrieve it.
                "instances",
                {
                    "data": [
                        {
                            "id": "i-1",
                            "jupyter_token": "secret-token",
                            "jupyter_url": "https://jupyter.lambda.ai/?token=secret-token",
                            "name": "gpu-box",
                        }
                    ]
                },
                [{"id": "i-1", "name": "gpu-box"}],
            ),
            (
                # The map endpoint hoists `instance_type` fields to the top level (including `name`,
                # the primary key) and keeps regional availability alongside them.
                "instance_types",
                {
                    "data": {
                        "gpu_1x_a100": {
                            "instance_type": {"name": "gpu_1x_a100", "price_cents_per_hour": 110},
                            "regions_with_capacity_available": [{"name": "us-west-1"}],
                        }
                    }
                },
                [
                    {
                        "name": "gpu_1x_a100",
                        "price_cents_per_hour": 110,
                        "regions_with_capacity_available": [{"name": "us-west-1"}],
                    }
                ],
            ),
            (
                # tickets nests its list one level deeper under `data.tickets`.
                "tickets",
                {"data": {"tickets": [{"id": "t1"}], "page_token": None}},
                [{"id": "t1"}],
            ),
            (
                "audit_events",
                {"data": [{"event_id": "e1"}], "page_token": None},
                [{"event_id": "e1"}],
            ),
        ],
    )
    def test_extract_records(self, endpoint: str, body: dict[str, Any], expected: list[dict[str, Any]]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.rows == expected


class TestFormatIso8601:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2025, 9, 15, 10, 30, 45, 123456, tzinfo=UTC), "2025-09-15T10:30:45.123Z"),
            # A naive datetime is treated as UTC rather than shifted by the machine's local zone.
            (datetime(2025, 1, 1, 0, 0, 0), "2025-01-01T00:00:00.000Z"),
            (date(2025, 3, 4), "2025-03-04T00:00:00.000Z"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_iso8601(value) == expected


class TestPaginationAndResume:
    def test_unpaginated_endpoint_yields_once_and_never_saves_state(self) -> None:
        result = _driver().run("instances", [ScriptedResponse(json={"data": [{"id": "i-1"}]})])

        assert result.raised is None
        assert result.rows == [{"id": "i-1"}]
        assert result.paths == ["/api/v1/instances"]
        assert result.saved_states == []

    def test_paginates_and_saves_state_after_each_non_terminal_page(self) -> None:
        result = _driver().run(
            "audit_events",
            [
                ScriptedResponse(json={"data": [{"event_id": "e1"}], "page_token": "tok-1"}),
                ScriptedResponse(json={"data": [{"event_id": "e2"}], "page_token": "tok-2"}),
                ScriptedResponse(json={"data": [{"event_id": "e3"}], "page_token": None}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"event_id": "e1"}, {"event_id": "e2"}, {"event_id": "e3"}]
        # First page carries no cursor; subsequent pages carry the prior page's token only.
        assert result.params("page_token") == [None, "tok-1", "tok-2"]
        # State is saved only for non-terminal pages, so a crash re-yields the last page.
        assert result.saved_states == [
            LambdaLabsResumeConfig(page_token="tok-1"),
            LambdaLabsResumeConfig(page_token="tok-2"),
        ]

    def test_resume_seeds_first_request_with_saved_token_only(self) -> None:
        result = _driver().run(
            "audit_events",
            [ScriptedResponse(json={"data": [{"event_id": "e9"}], "page_token": None})],
            resume_state=LambdaLabsResumeConfig(page_token="tok-resumed"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 1, 1, tzinfo=UTC),
        )

        # On resume the cursor already encodes the window, so only the token is sent — never `start`.
        assert result.raised is None
        assert result.queries == [{"page_token": ("tok-resumed",)}]

    def test_incremental_first_sync_sends_start_filter(self) -> None:
        result = _driver().run(
            "audit_events",
            [ScriptedResponse(json={"data": [{"event_id": "e1"}], "page_token": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.queries == [{"start": ("2025-06-01T12:00:00.000Z",)}]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (200, True),
        ],
    )
    def test_status_maps_to_bool(self, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("secret_key") is expected

        assert [request.path for request in network.requests_log] == ["/api/v1/ssh-keys"]

    def test_transient_error_propagates(self) -> None:
        # A 5xx is not a credential rejection — it must propagate so the caller reports a transient
        # failure rather than telling the user to rotate a valid key.
        with scripted_network(always(ScriptedResponse(status=503))):
            with pytest.raises(requests.HTTPError):
                validate_credentials("secret_key")
