import re
import json
import dataclasses
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.greenhouse import (
    GREENHOUSE_ENDPOINTS,
    PAGE_SIZE,
    V3_ONLY_ENDPOINT_ERROR,
    GreenhouseResumeConfig,
    _build_auth,
    _build_initial_params,
    _format_datetime,
    greenhouse_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.settings import (
    ENDPOINTS,
    GREENHOUSE_V1,
    GREENHOUSE_V3,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the greenhouse module.
GREENHOUSE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.greenhouse.make_tracked_session"
)
OAUTH_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth"


def _make_response(body: Any, status_code: int = 200, next_url: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    if next_url is not None:
        # RFC 5988 Link header, as Harvest returns it. requests parses this into `resp.links`.
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


def _make_manager(resume_state: GreenhouseResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _source(endpoint: str, **kwargs: Any) -> Any:
    # Transport tests run on v1: its HTTP Basic auth needs no token exchange, so the only network
    # boundary is the patched rest_client session. Version-specific request shape is covered by the
    # param/auth/url tests below. v3-only endpoints build on v3; the token is minted lazily on the
    # first request, so building the response needs no network.
    kwargs.setdefault("resumable_source_manager", _make_manager())
    kwargs.setdefault("api_version", GREENHOUSE_V3 if GREENHOUSE_ENDPOINTS[endpoint].v3_only else GREENHOUSE_V1)
    return greenhouse_source(
        endpoint, team_id=1, job_id="j", api_key="key", client_id="cid", client_secret="csecret", **kwargs
    )


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),  # naive -> treated as UTC
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected


WATERMARK = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)


class TestBuildInitialParams:
    @pytest.mark.parametrize(
        "endpoint, api_version, incremental_field, expected_filter",
        [
            # v1 filters through a separate `*_after` param; v3 filters on the field itself with a
            # pipe-delimited operator. Sending one version's syntax to the other silently drops the
            # filter (full re-sync every run) or 422s.
            ("candidates", GREENHOUSE_V1, "updated_at", {"updated_after": "2026-03-04T02:58:14.000Z"}),
            ("candidates", GREENHOUSE_V3, "updated_at", {"updated_at": "gte|2026-03-04T02:58:14.000Z"}),
            ("candidates", GREENHOUSE_V1, "created_at", {"created_after": "2026-03-04T02:58:14.000Z"}),
            ("candidates", GREENHOUSE_V3, "created_at", {"created_at": "gte|2026-03-04T02:58:14.000Z"}),
            ("applications", GREENHOUSE_V1, "last_activity_at", {"last_activity_after": "2026-03-04T02:58:14.000Z"}),
            ("applications", GREENHOUSE_V3, "last_activity_at", {"last_activity_at": "gte|2026-03-04T02:58:14.000Z"}),
            ("candidates", GREENHOUSE_V1, "somethingElse", {}),
            ("candidates", GREENHOUSE_V3, "somethingElse", {}),
        ],
    )
    def test_incremental_filter_syntax_per_version(
        self, endpoint: str, api_version: str, incremental_field: str, expected_filter: dict[str, str]
    ) -> None:
        params = _build_initial_params(GREENHOUSE_ENDPOINTS[endpoint], api_version, True, WATERMARK, incremental_field)
        assert params == {"per_page": PAGE_SIZE, **expected_filter}


class TestBuildAuth:
    @pytest.mark.parametrize(
        "api_version, api_key, client_id, client_secret",
        [
            (GREENHOUSE_V3, "test_key", None, None),
            (GREENHOUSE_V3, "test_key", "cid", None),
            (GREENHOUSE_V1, None, "cid", "csecret"),
        ],
    )
    def test_credentials_for_the_other_version_are_rejected(
        self, api_version: str, api_key: str | None, client_id: str | None, client_secret: str | None
    ) -> None:
        with pytest.raises(ValueError):
            _build_auth(api_version, api_key, client_id, client_secret)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, accept_forbidden, expected_valid",
        [
            (200, True, True),
            (200, False, True),
            (401, True, False),
            (401, False, False),
            (403, True, True),  # source-create: a scoped key may legitimately 403
            (403, False, False),  # per-schema check: missing scope is an error
            (500, True, False),
        ],
    )
    @mock.patch(GREENHOUSE_SESSION_PATCH)
    def test_status_code_mapping(
        self, mock_session_factory: MagicMock, status_code: int, accept_forbidden: bool, expected_valid: bool
    ) -> None:
        mock_session_factory.return_value.get.return_value = MagicMock(status_code=status_code)

        is_valid, error = validate_credentials(GREENHOUSE_V1, api_key="test_key", accept_forbidden=accept_forbidden)

        assert is_valid is expected_valid
        assert (error is None) is expected_valid

    @mock.patch(GREENHOUSE_SESSION_PATCH)
    def test_per_schema_forbidden_surfaces_scope_error(self, mock_session_factory: MagicMock) -> None:
        mock_session_factory.return_value.get.return_value = MagicMock(status_code=403)
        is_valid, error = validate_credentials(
            GREENHOUSE_V1, api_key="test_key", path="/candidates", accept_forbidden=False
        )
        assert is_valid is False
        assert error is not None and "permission" in error

    @mock.patch(GREENHOUSE_SESSION_PATCH)
    def test_network_error_is_not_valid(self, mock_session_factory: MagicMock) -> None:
        # validate_via_probe swallows transport errors and reports "not validated".
        mock_session_factory.return_value.get.side_effect = Exception("boom")
        is_valid, error = validate_credentials(GREENHOUSE_V1, api_key="test_key")
        assert is_valid is False
        assert error is not None

    @pytest.mark.parametrize(
        "api_version, expected_url",
        [
            (GREENHOUSE_V1, "https://harvest.greenhouse.io/v1/candidates?per_page=1"),
            (GREENHOUSE_V3, "https://harvest.greenhouse.io/v3/candidates?per_page=1"),
        ],
    )
    @mock.patch(f"{OAUTH_MODULE}.OAuth2Auth._obtain_token")
    @mock.patch(GREENHOUSE_SESSION_PATCH)
    def test_probes_the_pinned_version(
        self, mock_session_factory: MagicMock, mock_mint: MagicMock, api_version: str, expected_url: str
    ) -> None:
        # A v1-pinned source probed on the v3 path (or vice versa) reports a working key as broken.
        mock_get = mock_session_factory.return_value.get
        mock_get.return_value = MagicMock(status_code=200)

        validate_credentials(api_version, api_key="test_key", client_id="cid", client_secret="csecret")

        assert mock_get.call_args.args[0] == expected_url

    def test_v3_without_client_credentials_explains_what_to_create(self) -> None:
        is_valid, error = validate_credentials(GREENHOUSE_V3, api_key="test_key")
        assert is_valid is False
        assert error is not None and "OAuth" in error


class TestGreenhouseSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partition_key_is_never_updated_at(self, endpoint: str) -> None:
        assert GREENHOUSE_ENDPOINTS[endpoint].partition_key not in ("updated_at", "last_activity_at")

    @pytest.mark.parametrize("endpoint", [name for name, config in GREENHOUSE_ENDPOINTS.items() if config.v3_only])
    def test_v3_only_endpoint_refuses_to_sync_on_v1(self, endpoint: str) -> None:
        with pytest.raises(ValueError, match=re.escape(V3_ONLY_ENDPOINT_ERROR)):
            _source(endpoint, api_version=GREENHOUSE_V1)


class TestGreenhousePaginationAndResume:
    """Drive the rest_source transport (via ``greenhouse_source``) with a mocked HTTP session."""

    def _wire(self, session: MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
        """Snapshot each request's (url, params) at prepare time and feed ``responses`` to send."""
        session.headers = {}
        sent: list[tuple[str, dict[str, Any]]] = []

        def _prepare(request: Any) -> MagicMock:
            sent.append((request.url, dict(request.params or {})))
            prepared = MagicMock()
            prepared.url = request.url
            return prepared

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = responses
        return sent

    def _rows(self, source_response: Any) -> list[Any]:
        return [row for page in source_response.items() for row in page]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fresh_run_follows_link_header(self, mock_factory: MagicMock) -> None:
        session = mock_factory.return_value
        next_url = "https://harvest.greenhouse.io/v1/candidates?per_page=500&page=2"
        sent = self._wire(
            session,
            [
                _make_response([{"id": 1}], next_url=next_url),
                _make_response([{"id": 2}]),  # no Link header -> last page
            ],
        )

        rows = self._rows(_source("candidates"))

        # First request hits the path with params; second follows the Link URL verbatim (no params).
        assert sent[0] == ("https://harvest.greenhouse.io/v1/candidates", {"per_page": PAGE_SIZE})
        assert sent[1] == (next_url, {})
        assert rows == [{"id": 1}, {"id": 2}]

    @pytest.mark.parametrize(
        "hostile_next_url",
        [
            "https://evil.example.com/v1/candidates?page=2",
            # An allowed hostname over a downgraded scheme still puts the credential on the wire.
            "http://harvest.greenhouse.io/v1/candidates?page=2",
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_origin_next_link_is_rejected_before_a_request_is_sent(
        self, mock_factory: MagicMock, hostile_next_url: str
    ) -> None:
        # The Link URL is followed verbatim, so a spoofed one would otherwise replay the
        # Authorization header (v3: a freshly minted Bearer token) to another origin.
        session = mock_factory.return_value
        self._wire(session, [_make_response([{"id": 1}], next_url=hostile_next_url)])

        with pytest.raises(ValueError):
            self._rows(_source("candidates"))

        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cross_origin_redirect_is_not_followed(self, mock_factory: MagicMock) -> None:
        session = mock_factory.return_value
        redirect = _make_response([], status_code=302)
        redirect.headers["Location"] = "https://evil.example.com/v1/candidates"
        self._wire(session, [redirect])

        with pytest.raises(ValueError):
            self._rows(_source("candidates"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_applied_to_first_request(self, mock_factory: MagicMock) -> None:
        session = mock_factory.return_value
        sent = self._wire(session, [_make_response([{"id": 1}])])

        watermark = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        self._rows(
            _source(
                "candidates",
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
                incremental_field="updated_at",
            )
        )

        assert sent[0][1] == {"per_page": PAGE_SIZE, "updated_after": "2026-03-04T02:58:14.000Z"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_first_request_with_saved_next_url(self, mock_factory: MagicMock) -> None:
        session = mock_factory.return_value
        saved_url = "https://harvest.greenhouse.io/v1/candidates?per_page=500&page=5"
        sent = self._wire(session, [_make_response([{"id": 9}])])

        manager = _make_manager(GreenhouseResumeConfig(next_url=saved_url))
        self._rows(_source("candidates", resumable_source_manager=manager))

        assert sent[0] == (saved_url, {})


class TestResumeConfigSerialization:
    def test_round_trip(self) -> None:
        cfg = GreenhouseResumeConfig(next_url="https://harvest.greenhouse.io/v1/candidates?page=3")
        reconstituted = GreenhouseResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg
