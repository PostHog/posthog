import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, PreparedRequest, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.frontegg import (
    FronteggAuth,
    FronteggResumeConfig,
    frontegg_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frontegg import (
    FronteggSourceConfig,
)

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.frontegg"
REST_CLIENT = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.url = "https://api.frontegg.com/auth/vendor"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


Region = Literal["EU", "US", "CA", "AU"]


def config(region: Region = "EU") -> FronteggSourceConfig:
    return FronteggSourceConfig(client_id="example-client", api_key="fake-api-key", region=region)


class TestFronteggTransport:
    @pytest.mark.parametrize("table,version", [("users", "v3"), ("roles", "v2")])
    @pytest.mark.parametrize("resume_page", [None, 1])
    @pytest.mark.parametrize("empty_terminal", [False, True])
    def test_pagination_and_resume(
        self, table: str, version: str, resume_page: int | None, empty_terminal: bool
    ) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = resume_page is not None
        manager.load_state.return_value = FronteggResumeConfig(page=resume_page or 0)
        inputs = MagicMock(spec=SourceInputs, schema_name=table, team_id=1, job_id="test-job")
        first_page = resume_page or 0
        pages = iter(
            [
                response({"items": [{"id": "first"}], "_metadata": {"totalPages": first_page + 2}}),
                response(
                    {"items": [] if empty_terminal else [{"id": "last"}], "_metadata": {"totalPages": first_page + 2}}
                ),
            ]
        )
        sent: list[PreparedRequest] = []

        def send(request: PreparedRequest, **kwargs: object) -> Response:
            sent.append(request)
            return next(pages)

        with (
            patch(f"{TRANSPORT}.make_tracked_session") as auth_session,
            patch(f"{REST_CLIENT}.make_tracked_session") as factory,
        ):
            auth_session.return_value.__enter__.return_value.post.return_value = response(
                {"token": "fake-token", "expiresIn": 3600}
            )
            session = Session()
            factory.return_value = session
            with patch.object(session, "send", side_effect=send):
                source = frontegg_source(config(), manager, inputs, "v3")
                rows = [row for batch in cast(Iterable[Any], source.items()) for row in batch]
        assert rows == [{"id": "first"}] + ([] if empty_terminal else [{"id": "last"}])
        assert len(sent) == 2
        for index, request in enumerate(sent):
            assert urlsplit(request.url or "").path == f"/identity/resources/{table}/{version}"
            assert parse_qs(urlsplit(request.url or "").query) == {
                "_limit": ["200"],
                "_offset": [str(first_page + index)],
                "_sortBy": ["createdAt"],
                "_order": ["ASC"],
            }
            assert request.headers["Authorization"] == "Bearer fake-token"
        manager.save_state.assert_called_once_with(FronteggResumeConfig(page=first_page + 1))

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
        with patch(f"{TRANSPORT}.make_tracked_session") as factory:
            post = factory.return_value.__enter__.return_value.post
            post.side_effect = [
                response({"token": "fake-first", "expiresIn": 3600}),
                response({"token": "fake-second", "expiresIn": 3600}),
            ]
            first = PreparedRequest()
            first.prepare(method="GET", url=f"https://{host}/identity/resources/users/v3")
            auth(first)
            assert first.headers["Authorization"] == "Bearer fake-first"
            auth(first)
            assert post.call_count == 1
            auth.token_expiry = datetime.now(UTC) - timedelta(seconds=1)
            auth(first)
            assert first.headers["Authorization"] == "Bearer fake-second"
            assert post.call_count == 2
            post.assert_called_with(
                f"https://{host}/auth/vendor",
                json={"clientId": "example-client", "secret": "fake-api-key"},
                timeout=(10, 30),
            )
            assert factory.call_args.kwargs["capture"] is False
            assert factory.call_args.kwargs["allow_redirects"] is False
            assert "fake-api-key" in auth.secret_values()
            assert "fake-second" in auth.secret_values()

    @pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 302])
    def test_token_http_errors(self, status: int) -> None:
        with patch(f"{TRANSPORT}.make_tracked_session") as factory:
            factory.return_value.__enter__.return_value.post.return_value = response({}, status)
            with pytest.raises(HTTPError):
                FronteggAuth(config())._obtain_token()

    def test_unknown_table(self) -> None:
        with pytest.raises(ValueError, match="Unsupported Frontegg table"):
            frontegg_source(config(), MagicMock(), MagicMock(schema_name="unknown"), "v3")

    def test_invalid_region(self) -> None:
        with pytest.raises(ValueError, match="Select a supported Frontegg region"):
            FronteggAuth(config(cast(Any, "https://example.com")))
