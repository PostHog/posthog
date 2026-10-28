from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import pytest

from requests import HTTPError, PreparedRequest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.frontegg import (
    FronteggAuth,
    FronteggResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.source import FronteggSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frontegg import (
    FronteggSourceConfig,
)

Region = Literal["EU", "US", "CA", "AU"]


def config(region: Region = "EU") -> FronteggSourceConfig:
    return FronteggSourceConfig(client_id="example-client", api_key="fake-api-key", region=region)


class TestFronteggTransport:
    @pytest.mark.parametrize(
        "table,endpoint_path",
        [
            ("users", "/identity/resources/users/v3"),
            ("roles", "/identity/resources/roles/v2"),
            ("tenants", "/tenants/resources/tenants/v2"),
        ],
    )
    @pytest.mark.parametrize("resume_page", [None, 1])
    @pytest.mark.parametrize("empty_terminal", [False, True])
    def test_pagination_and_resume(
        self, table: str, endpoint_path: str, resume_page: int | None, empty_terminal: bool
    ) -> None:
        first_page = resume_page or 0
        result = SourceDriver(FronteggSource(), config()).run(
            table,
            [
                ScriptedResponse(json={"token": "fake-token", "expiresIn": 3600}),
                ScriptedResponse(json={"items": [{"id": "first"}], "_metadata": {"totalPages": first_page + 2}}),
                ScriptedResponse(
                    json={
                        "items": [] if empty_terminal else [{"id": "last"}],
                        "_metadata": {"totalPages": first_page + 2},
                    }
                ),
            ],
            resume_state=FronteggResumeConfig(page=resume_page) if resume_page is not None else None,
        )
        assert result.raised is None
        assert result.rows == [{"id": "first"}] + ([] if empty_terminal else [{"id": "last"}])
        assert result.paths == ["/auth/vendor", endpoint_path, endpoint_path]
        for index, request in enumerate(result.requests[1:]):
            assert request.query == {
                "_limit": ("200",),
                "_offset": (str(first_page + index),),
                "_sortBy": ("createdAt",),
                "_order": ("ASC",),
            }
            assert request.headers["authorization"] == "Bearer fake-token"
        assert result.saved_states == [FronteggResumeConfig(page=first_page + 1)]

    @pytest.mark.parametrize(
        "should_use_incremental_field,last_value,created_from",
        [
            (False, datetime(2026, 1, 2, 3, 4, 5), None),
            (True, None, None),
            (True, datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05+00:00"),
        ],
    )
    @pytest.mark.parametrize(
        "resume",
        [
            None,
            FronteggResumeConfig(offset=200),
            FronteggResumeConfig(offset=200, created_from="2025-12-01T00:00:00+00:00"),
        ],
    )
    def test_audits_offset_pagination_incremental_and_resume(
        self,
        should_use_incremental_field: bool,
        last_value: datetime | None,
        created_from: str | None,
        resume: FronteggResumeConfig | None,
    ) -> None:
        first_offset = resume.offset if resume and resume.offset is not None else 0
        window = resume.created_from if resume else created_from
        full_page = [{"frontegg_id": f"event-{index}"} for index in range(200)]
        result = SourceDriver(FronteggSource(), config()).run(
            "audits",
            [
                ScriptedResponse(json={"token": "fake-token", "expiresIn": 3600}),
                ScriptedResponse(json={"data": full_page, "total": first_offset + 201}),
                ScriptedResponse(json={"data": [{"frontegg_id": "last"}], "total": first_offset + 201}),
            ],
            resume_state=resume,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        assert result.raised is None
        assert result.rows == [*full_page, {"frontegg_id": "last"}]
        assert result.paths == ["/auth/vendor", "/audits/resources/audits/v2", "/audits/resources/audits/v2"]
        for index, request in enumerate(result.requests[1:]):
            expected = {
                "count": ("200",),
                "offset": (str(first_offset + index * 200),),
                "sortBy": ("createdAt",),
                "sortDirection": ("asc",),
            }
            if window is not None:
                expected["created_from"] = (window,)
            assert request.query == expected
        assert result.saved_states == [FronteggResumeConfig(offset=first_offset + 200, created_from=window)]

    @pytest.mark.parametrize(
        "region,host",
        [
            ("EU", "api.frontegg.com"),
            ("US", "api.us.frontegg.com"),
            ("CA", "api.ca.frontegg.com"),
            ("AU", "api.au.frontegg.com"),
        ],
    )
    def test_token_exchange_refresh_and_redaction(self, region: Region, host: str) -> None:
        auth = FronteggAuth(config(region))
        with scripted_network(
            [
                ScriptedResponse(json={"token": "fake-first", "expiresIn": 3600}),
                ScriptedResponse(json={"token": "fake-second", "expiresIn": 3600}),
            ]
        ) as network:
            first = PreparedRequest()
            first.prepare(method="GET", url=f"https://{host}/identity/resources/users/v3")
            auth(first)
            assert first.headers["Authorization"] == "Bearer fake-first"
            auth(first)
            assert len(network.requests_log) == 1
            auth.token_expiry = datetime.now(UTC) - timedelta(seconds=1)
            auth(first)
            assert first.headers["Authorization"] == "Bearer fake-second"
            assert len(network.requests_log) == 2
            last = network.requests_log[-1]
            assert last.method == "POST"
            assert last.url == f"https://{host}/auth/vendor"
            assert last.json() == {"clientId": "example-client", "secret": "fake-api-key"}
            assert all(options["capture"] is False for options in network.session_options)
            assert all(options["allow_redirects"] is False for options in network.session_options)
            assert "fake-api-key" in auth.secret_values()
            assert "fake-second" in auth.secret_values()

    @pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 302])
    def test_token_http_errors(self, status: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            with pytest.raises(HTTPError):
                FronteggAuth(config())._obtain_token()
        assert {request.path for request in network.requests_log} == {"/auth/vendor"}

    def test_invalid_region(self) -> None:
        with pytest.raises(ValueError, match="Select a supported Frontegg region"):
            FronteggAuth(config(cast(Any, "https://example.com")))
