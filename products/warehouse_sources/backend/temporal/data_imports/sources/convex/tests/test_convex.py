from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

from django.test import override_settings

import structlog
from parameterized import parameterized
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    ReadTimeout,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex import (
    _CONVEX_RETRY,
    ConvexDataSyncCursor,
    ConvexResumeConfig,
    ConvexResyncRequiredError,
    InvalidDeployKeyError,
    InvalidDeployUrlError,
    StreamingExportNotEnabledError,
    _convex_post,
    get_json_schemas,
    iter_component_tables,
    qualified_table_name,
    split_qualified_table_name,
    validate_credentials,
    validate_deploy_key,
    validate_deploy_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.convex.source import ConvexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.convex import ConvexSourceConfig


def _make_response(json_data: dict[str, Any], status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    response.raise_for_status = Mock()
    return response


class TestValidateDeployUrl:
    @parameterized.expand(
        [
            # Valid URLs normalize to a clean https://host.
            ("simple", "https://swift-lemur-123.convex.cloud", "https://swift-lemur-123.convex.cloud"),
            ("trailing_slash", "https://swift-lemur-123.convex.cloud/", "https://swift-lemur-123.convex.cloud"),
            ("uppercase", "HTTPS://Swift-Lemur-123.CONVEX.CLOUD", "https://swift-lemur-123.convex.cloud"),
            ("leading_space", "  https://swift-lemur-123.convex.cloud", "https://swift-lemur-123.convex.cloud"),
            ("with_path", "https://swift-lemur-123.convex.cloud/some/path", "https://swift-lemur-123.convex.cloud"),
            (
                "regional_eu_west_1",
                "https://breezy-otter-42.eu-west-1.convex.cloud",
                "https://breezy-otter-42.eu-west-1.convex.cloud",
            ),
            (
                "regional_us_east_1",
                "https://clever-falcon-77.us-east-1.convex.cloud",
                "https://clever-falcon-77.us-east-1.convex.cloud",
            ),
            # A missing scheme normalizes by prepending https://.
            ("no_scheme", "swift-lemur-123.convex.cloud", "https://swift-lemur-123.convex.cloud"),
            (
                "no_scheme_regional",
                "breezy-otter-42.eu-west-1.convex.cloud",
                "https://breezy-otter-42.eu-west-1.convex.cloud",
            ),
            ("no_scheme_trailing_slash", "swift-lemur-123.convex.cloud/", "https://swift-lemur-123.convex.cloud"),
            # Invalid URLs must be rejected.
            ("http", "http://swift-lemur-123.convex.cloud", None),
            ("ftp", "ftp://swift-lemur-123.convex.cloud", None),
            ("wrong_tld", "https://swift-lemur-123.convex.io", None),
            ("two_extra_subdomains", "https://extra.foo.swift-lemur-123.convex.cloud", None),
            ("lookalike", "https://convex.cloud.evil.com", None),
            ("bare_domain", "https://convex.cloud", None),
            ("ip_literal", "https://1.2.3.4", None),
            ("localhost", "https://localhost", None),
            ("metadata_ip", "https://169.254.169.254", None),
            ("internal_domain", "https://swift-lemur-123.convex.cloud.internal", None),
            ("query_params", "https://swift-lemur-123.convex.cloud?evil=1", None),
            ("fragment", "https://swift-lemur-123.convex.cloud#section", None),
        ]
    )
    def test_validate_deploy_url(self, _name, url, expected):
        if expected is not None:
            assert validate_deploy_url(url) == expected
        else:
            with pytest.raises(InvalidDeployUrlError):
                validate_deploy_url(url)

    @parameterized.expand(
        [
            ("bad_url", "http://169.254.169.254", "deploy-key"),
            ("unsendable_key", "https://swift-lemur-123.convex.cloud", "prod:swift-lemur-123|ab\u2028cd"),
            ("blank_key", "https://swift-lemur-123.convex.cloud", "   "),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_validate_credentials_rejects_bad_input_without_network_call(self, _name, url, deploy_key, mock_get):
        ok, err = validate_credentials(url, deploy_key)
        assert not ok
        assert err is not None
        mock_get.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_validate_credentials_accepts_valid_url(self, mock_get):
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        ok, err = validate_credentials("https://swift-lemur-123.convex.cloud", "prod:abc123")
        assert ok
        assert err is None
        called_url = mock_get.return_value.get.call_args.args[0]
        assert called_url.startswith("https://swift-lemur-123.convex.cloud/api/")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_validate_credentials_surfaces_streaming_export_message(self, mock_get):
        mock_get.return_value.get.return_value = _make_response({"code": "StreamingExportNotEnabled"}, status_code=400)

        ok, err = validate_credentials("https://swift-lemur-123.convex.cloud", "prod:abc123")

        assert not ok
        assert err == (
            "Streaming export requires the Convex Professional plan. See https://www.convex.dev/plans to upgrade."
        )

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_validate_credentials_does_not_leak_url_on_http_error(self, mock_get):
        err_response = Mock(status_code=400)
        err_response.json.return_value = {"code": "SomethingUnexpected"}
        response = Mock()
        response.raise_for_status.side_effect = HTTPError(response=err_response)
        mock_get.return_value.get.return_value = response

        ok, err = validate_credentials("https://swift-lemur-123.convex.cloud", "prod:abc123")
        assert not ok
        assert err is not None
        assert "swift-lemur-123" not in err
        assert "convex.cloud" not in err
        assert "400" in err

    @parameterized.expand(
        [
            ("same_deployment", "prod:swift-lemur-123|abc", "Convex rejected your deploy key."),
            ("unnamed_key", "abc123", "Convex rejected your deploy key."),
            ("dev_key_for_prod_url", "dev:quiet-otter-456|abc", "belongs to a different Convex deployment"),
            ("key_for_other_project", "prod:quiet-otter-456|abc", "belongs to a different Convex deployment"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_validate_credentials_explains_a_rejected_deploy_key(self, _name, deploy_key, expected, mock_get):
        response = Mock()
        response.raise_for_status.side_effect = HTTPError(response=Mock(status_code=401))
        mock_get.return_value.get.return_value = response

        ok, err = validate_credentials("https://swift-lemur-123.eu-west-1.convex.cloud", deploy_key)

        assert not ok
        assert err is not None
        assert expected in err
        assert "swift-lemur-123" not in err
        assert "quiet-otter-456" not in err


class TestValidateDeployKey:
    @parameterized.expand(
        [
            ("plain", "prod:swift-lemur-123|abc", "prod:swift-lemur-123|abc"),
            ("surrounding_spaces", "  prod:swift-lemur-123|abc  ", "prod:swift-lemur-123|abc"),
            ("trailing_newline", "prod:swift-lemur-123|abc\n", "prod:swift-lemur-123|abc"),
            # A key copied out of a browser can carry an invisible separator that latin-1 cannot
            # encode. Both are whitespace to str.strip, so a key that only has one at either end
            # stays usable.
            ("trailing_line_separator", "prod:swift-lemur-123|abc\u2028", "prod:swift-lemur-123|abc"),
            ("leading_no_break_space", "\u00a0prod:swift-lemur-123|abc", "prod:swift-lemur-123|abc"),
            # invalid - should raise
            ("blank", "   ", None),
            ("embedded_line_separator", "prod:swift-lemur\u2028-123|abc", None),
            ("embedded_non_latin_1", "prod:swift-lemur-123|ab\u2603cd", None),
        ]
    )
    def test_validate_deploy_key(self, _name: str, deploy_key: str, expected: str | None) -> None:
        if expected is not None:
            cleaned = validate_deploy_key(deploy_key)
            assert cleaned == expected
            cleaned.encode("latin-1")
        else:
            with pytest.raises(InvalidDeployKeyError):
                validate_deploy_key(deploy_key)


class TestComponentSupport:
    @parameterized.expand(
        [
            # Root-component tables keep their bare name so existing synced tables are unaffected.
            ("root", "", "users", "users"),
            ("single_component", "betterAuth", "users", "betterAuth.users"),
            # Convex nests component paths with "/"; the table name is still the segment after the
            # final ".", so the round-trip must recover the full path.
            ("nested_component", "parent/child", "users", "parent/child.users"),
        ]
    )
    def test_qualified_table_name_round_trips(
        self, _name: str, component_path: str, table_name: str, expected_qualified: str
    ) -> None:
        qualified = qualified_table_name(component_path, table_name)
        assert qualified == expected_qualified
        assert split_qualified_table_name(qualified) == (component_path, table_name)

    @parameterized.expand(
        [
            # The byComponent shape uses the empty key for the root component.
            (
                "grouped_by_component",
                {
                    "": {"users": {"type": "object"}, "messages": {"type": "object"}},
                    "betterAuth": {"users": {"type": "object"}},
                },
                [("", "users"), ("", "messages"), ("betterAuth", "users")],
            ),
            # Legacy deployments ignore byComponent and return the flat {table: schema} shape; every
            # table is then a root-component table.
            (
                "legacy_flat",
                {"users": {"type": "object"}, "messages": {"type": "object"}},
                [("", "users"), ("", "messages")],
            ),
            # `type`/`properties` are valid Convex table names: the "" root key must classify the
            # response as grouped, not a schema-key inspection that misfires on such a table.
            (
                "grouped_with_table_named_type",
                {"": {"type": {"type": "object"}}, "betterAuth": {"users": {"type": "object"}}},
                [("", "type"), ("betterAuth", "users")],
            ),
            ("empty", {}, []),
        ]
    )
    def test_iter_component_tables(
        self, _name: str, schemas_response: dict[str, Any], expected: list[tuple[str, str]]
    ) -> None:
        assert sorted(iter_component_tables(schemas_response)) == sorted(expected)


class TestConvexRetryPolicy:
    @parameterized.expand(
        [
            # Convex sits behind Cloudflare and emits the 52x family on transient
            # edge/origin trouble. The 520 here is the exact code that fails syncs in production.
            ("cf_520_unknown_error", 520, True),
            ("cf_521_web_server_down", 521, True),
            ("cf_522_connection_timed_out", 522, True),
            ("cf_523_origin_unreachable", 523, True),
            ("cf_524_timeout", 524, True),
            ("cf_530_dns_error", 530, True),
            # Standard transient codes inherited from DEFAULT_RETRY must still be retried.
            ("rate_limited_429", 429, True),
            ("internal_500", 500, True),
            ("bad_gateway_502", 502, True),
            ("service_unavailable_503", 503, True),
            ("gateway_timeout_504", 504, True),
            # Client errors are not transient, so they must not be retried away.
            ("bad_request_400", 400, False),
            ("unauthorized_401", 401, False),
            ("forbidden_403", 403, False),
            ("not_found_404", 404, False),
        ]
    )
    def test_retry_status_handling(self, _name: str, status_code: int, expected_retry: bool) -> None:
        for method in ("GET", "POST"):
            assert _CONVEX_RETRY.is_retry(method, status_code) is expected_retry


class TestConvexNonRetryableErrors:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_streaming_export_not_enabled_message_is_recognised_as_non_retryable(self, mock_get: Mock) -> None:
        # get_schemas (schema discovery) calls get_json_schemas directly, unlike
        # validate_credentials which already inspected the response body for this code. Without
        # get_json_schemas surfacing the code itself, discovery only ever saw a bare HTTPError
        # whose message never matches the "StreamingExportNotEnabled" non-retryable entry below.
        mock_get.return_value.get.return_value = _make_response({"code": "StreamingExportNotEnabled"}, status_code=400)

        with pytest.raises(StreamingExportNotEnabledError) as exc_info:
            get_json_schemas("https://x.convex.cloud", "key")

        error_msg = str(exc_info.value)
        non_retryable_errors = ConvexSource().get_non_retryable_errors()
        assert any(key in error_msg for key in non_retryable_errors), error_msg

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_get_json_schemas_400_with_unparseable_body_falls_through_to_http_error(self, mock_get: Mock) -> None:
        # A 400 whose body isn't JSON (e.g. a proxy/edge error page) must not crash the
        # body-parsing added for StreamingExportNotEnabled detection - it should fall through
        # to the normal raise_for_status() error instead of raising an unhandled ValueError.
        response = _make_response({}, status_code=400)
        response.json.side_effect = ValueError("not JSON")
        response.raise_for_status.side_effect = HTTPError(response=response)
        mock_get.return_value.get.return_value = response

        with pytest.raises(HTTPError):
            get_json_schemas("https://x.convex.cloud", "key")

    @parameterized.expand(
        [
            ("401", "401 Client Error: Unauthorized for url: https://x.convex.cloud/api/v1/data/sync"),
            ("403", "403 Client Error: Forbidden for url: https://x.convex.cloud/api/v1/data/sync"),
            (
                "missing_table_404",
                "404 Client Error: Not Found for url: https://x.convex.cloud/api/v1/data/sync",
            ),
            (
                "cursor_conflict_409",
                "409 Client Error: Conflict for url: https://x.convex.cloud/api/v1/data/sync",
            ),
            (
                "unsendable_deploy_key",
                "Your deploy key contains characters PostHog can't send to Convex. "
                "Copy the key again from your Convex dashboard, then try again.",
            ),
        ]
    )
    def test_known_errors_match(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = ConvexSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error for url: https://x.convex.cloud/api/v1/data/sync"),
            ("read_timeout", "HTTPSConnectionPool(host='x.convex.cloud', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_do_not_match(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = ConvexSource().get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable_errors)


class TestConvexRetryableErrors:
    @parameterized.expand(
        [
            (
                "500",
                "500 Server Error: Internal Server Error for url: https://x.convex.cloud/api/v1/data/sync",
            ),
            ("502", "502 Server Error: Bad Gateway for url: https://x.convex.cloud/api/v1/data/sync"),
            ("503", "503 Server Error: Service Unavailable for url: https://x.convex.cloud/api/v1/data/sync"),
            ("504", "504 Server Error: Gateway Timeout for url: https://x.convex.cloud/api/v1/data/sync"),
            ("cloudflare_520", "520 Server Error: Unknown Error for url: https://x.convex.cloud/api/v1/data/sync"),
            ("429", "429 Client Error: Too Many Requests for url: https://x.convex.cloud/api/v1/data/sync"),
        ]
    )
    def test_transient_errors_are_recognized_as_retryable(self, _name: str, observed_error: str) -> None:
        retryable_errors = ConvexSource().get_retryable_errors()
        assert any(key in observed_error for key in retryable_errors), observed_error

    @parameterized.expand(
        [
            ("401", "401 Client Error: Unauthorized for url: https://x.convex.cloud/api/v1/data/sync"),
            ("403", "403 Client Error: Forbidden for url: https://x.convex.cloud/api/v1/data/sync"),
            ("409", "409 Client Error: Conflict for url: https://x.convex.cloud/api/v1/data/sync"),
        ]
    )
    def test_non_retryable_errors_do_not_match(self, _name: str, observed_error: str) -> None:
        retryable_errors = ConvexSource().get_retryable_errors()
        assert not any(key in observed_error for key in retryable_errors), observed_error


@pytest.fixture
def redis_boundary() -> Iterator[Mock]:
    values: dict[str, str] = {}
    client = Mock()
    client.exists.side_effect = lambda key: int(key in values)
    client.get.side_effect = values.get
    client.set.side_effect = lambda key, value, **kwargs: values.update({key: value})
    client.delete.side_effect = lambda key: values.pop(key, None)
    with (
        override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT=6379),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
            return_value=client,
        ),
    ):
        yield client


@pytest.fixture
def http_boundary() -> Iterator[Mock]:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session"
    ) as factory:
        yield factory.return_value


def _inputs(
    incremental: bool = True,
    stored: str | None = None,
    watermark: int | None = None,
    table: str = "users",
) -> SourceInputs:
    source = ConvexSource()
    return SourceInputs(
        schema_name=table,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
        db_incremental_field_earliest_value=None,
        incremental_field="_ts" if incremental else None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
        source_cursor=SourceCursorManager(
            ConvexDataSyncCursor,
            ConvexDataSyncCursor(cursor=stored) if stored else None,
            source,
        ),
    )


def _resource(inputs: SourceInputs, manager: ResumableSourceManager[ConvexResumeConfig]) -> SourceResponse:
    return ConvexSource().source_for_pipeline(
        ConvexSourceConfig(deploy_url="https://x.convex.cloud", deploy_key="key"), manager, inputs
    )


def _items(resource: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], resource.items())


_convex_post_retry = cast(Any, _convex_post).retry


def _page(
    cursor: str,
    status: str = "upToDate",
    has_more: bool = True,
    values: list[dict[str, Any]] | None = None,
    truncates: list[dict[str, str]] | None = None,
) -> Mock:
    return _make_response(
        {
            "status": {"type": status},
            "values": values or [],
            "truncates": truncates or [],
            "syncId": "sync-id",
            "pagination": {"nextCursor": cursor, "hasMore": has_more},
        }
    )


@pytest.mark.parametrize(
    "table,component", [("users", ""), ("auth.users", "auth"), ("parent/child.users", "parent/child")]
)
def test_single_table_selection_and_legacy_rows(
    table: str, component: str, redis_boundary: Mock, http_boundary: Mock
) -> None:
    inputs = _inputs(table=table)
    manager = ConvexSource().get_resumable_source_manager(inputs)
    http_boundary.post.return_value = _page(
        "end",
        values=[
            {
                "component": component,
                "table": "users",
                "ts": 100,
                "deleted": False,
                "value": {"_id": "a", "_creationTime": 1700000000000, "name": "Example"},
            },
            {"component": component, "table": "users", "ts": 101, "deleted": True, "value": {"_id": "b"}},
        ],
    )
    resource = _resource(inputs, manager)
    assert list(_items(resource)) == [
        [
            {"_id": "a", "_creationTime": 1700000000, "name": "Example", "_ts": 100, "_deleted": False},
            {"_id": "b", "_ts": 101, "_deleted": True},
        ]
    ]
    request = http_boundary.post.call_args
    assert request.args[0] == "https://x.convex.cloud/api/v1/data/sync"
    assert request.kwargs["json"] == {
        "selection": {"_other": "excluded", component: {"_other": "excluded", "users": {"_other": "included"}}}
    }
    assert request.kwargs["headers"]["Authorization"] == "Convex key"
    assert resource.name == table
    assert resource.primary_keys == ["_id"]
    assert (resource.partition_keys, resource.partition_format) == (["_creationTime"], "week")


def test_full_refresh_reads_one_list_snapshot(redis_boundary: Mock, http_boundary: Mock) -> None:
    inputs = _inputs(incremental=False, stored="ignored", table="auth.users")
    manager = ConvexSource().get_resumable_source_manager(inputs)
    http_boundary.get.side_effect = [
        _make_response({"values": [{"_id": "a", "_ts": 1}], "cursor": "c1", "snapshot": 5, "hasMore": True}),
        _make_response({"values": [{"_id": "b", "_ts": 2}], "cursor": "c2", "snapshot": 5, "hasMore": False}),
    ]
    assert list(_items(_resource(inputs, manager))) == [[{"_id": "a", "_ts": 1}], [{"_id": "b", "_ts": 2}]]
    http_boundary.post.assert_not_called()
    first, second = http_boundary.get.call_args_list
    assert first.args[0] == "https://x.convex.cloud/api/list_snapshot"
    assert first.kwargs["params"] == {"tableName": "users", "format": "json", "component": "auth"}
    assert (second.kwargs["params"]["cursor"], second.kwargs["params"]["snapshot"]) == ("c1", 5)
    assert inputs.source_cursor is not None
    assert inputs.source_cursor.staged is None


def test_legacy_watermark_converts_once_and_retries_from_saved_cursor(
    redis_boundary: Mock, http_boundary: Mock
) -> None:
    inputs = _inputs(watermark=123, table="auth.users")
    manager = ConvexSource().get_resumable_source_manager(inputs)
    http_boundary.post.side_effect = [
        _make_response({"cursor": "converted"}),
        ReadTimeout("interrupted"),
    ]
    with patch.object(_convex_post_retry, "stop", return_value=True), pytest.raises(ReadTimeout):
        list(_items(_resource(inputs, manager)))
    assert http_boundary.post.call_args_list[0].args[0].endswith("/api/data_sync_cursor_from_deltas")
    assert http_boundary.post.call_args_list[0].kwargs["json"] == {
        "cursor": 123,
        "selection": {"_other": "excluded", "auth": {"_other": "excluded", "users": {"_other": "included"}}},
    }
    http_boundary.post.side_effect = None
    http_boundary.post.return_value = _page("end")
    list(_items(_resource(inputs, ConvexSource().get_resumable_source_manager(inputs))))
    assert http_boundary.post.call_args.kwargs["json"]["cursor"] == "converted"
    assert (
        sum(call.args[0].endswith("/api/data_sync_cursor_from_deltas") for call in http_boundary.post.call_args_list)
        == 1
    )


@pytest.mark.parametrize("failure", [404, 400, 403, "invalid_response"])
def test_refused_legacy_conversion_requests_reset(
    failure: int | str, redis_boundary: Mock, http_boundary: Mock
) -> None:
    inputs = _inputs(watermark=123)
    manager = ConvexSource().get_resumable_source_manager(inputs)
    if isinstance(failure, int):
        response = _make_response({}, status_code=failure)
        response.raise_for_status.side_effect = HTTPError(f"{failure} Client Error", response=response)
        http_boundary.post.return_value = response
    else:
        http_boundary.post.return_value = _make_response({})
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.update_sync_type_config_keys"
        ) as reset,
        patch.object(_convex_post_retry, "stop", return_value=True),
        pytest.raises(ConvexResyncRequiredError, match="legacy sync position") as error,
    ):
        list(_items(_resource(inputs, manager)))
    reset.assert_called_once_with("schema-id", 1, updates={"reset_pipeline": True})
    source = ConvexSource()
    assert not error_message_matches(str(error.value), source.get_non_retryable_errors())
    assert error_message_matches(str(error.value), source.get_retryable_errors())
    assert http_boundary.post.call_count == 1


@pytest.mark.parametrize("failure", [500, 429, "connection"])
def test_transient_legacy_conversion_failure_retries_without_reset(
    failure: int | str, redis_boundary: Mock, http_boundary: Mock
) -> None:
    inputs = _inputs(watermark=123)
    manager = ConvexSource().get_resumable_source_manager(inputs)
    if isinstance(failure, int):
        response = _make_response({}, status_code=failure)
        response.raise_for_status.side_effect = HTTPError(f"{failure} Error", response=response)
        http_boundary.post.return_value = response
        expected: type[Exception] = HTTPError
    else:
        http_boundary.post.side_effect = RequestsConnectionError("unavailable")
        expected = RequestsConnectionError
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.update_sync_type_config_keys"
        ) as reset,
        patch.object(_convex_post_retry, "stop", return_value=True),
        patch.object(_convex_post_retry, "sleep"),
        pytest.raises(expected),
    ):
        list(_items(_resource(inputs, manager)))
    reset.assert_not_called()


@pytest.mark.parametrize("origin", ["stored", "converted", "in_run", "fresh", "fresh_in_run"])
@pytest.mark.parametrize("event", ["truncate", "expired"])
def test_truncates_and_expiry_reset_only_when_required(
    origin: str, event: str, redis_boundary: Mock, http_boundary: Mock
) -> None:
    inputs = _inputs(
        stored="stored" if origin == "stored" else None,
        watermark=123 if origin == "converted" else None,
        table="auth.users",
    )
    manager = ConvexSource().get_resumable_source_manager(inputs)
    scoped = manager.with_namespace("data_sync")
    if origin in ("in_run", "fresh_in_run"):
        with scoped.committing():
            scoped.save_state(ConvexResumeConfig(cursor="resumed", started_from_cursor=origin == "in_run"))
    if event == "truncate":
        page = _page(
            "end",
            values=[{"value": {"_id": "replacement"}, "ts": 999, "deleted": False}],
            truncates=[{"component": "auth", "table": "users"}],
        )
    else:
        page = _make_response({"code": "DataSyncCursorExpired"}, status_code=400)
    http_boundary.post.side_effect = (
        [_make_response({"cursor": "converted"}), page] if origin == "converted" else [page]
    )
    requires_reset = event == "expired" or origin in ("stored", "converted", "in_run")
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.update_sync_type_config_keys"
    ) as reset:
        if requires_reset:
            with pytest.raises(ConvexResyncRequiredError) as error:
                list(_items(_resource(inputs, manager)))
            reset.assert_called_once_with("schema-id", 1, updates={"reset_pipeline": True})
            assert not error_message_matches(str(error.value), ConvexSource().get_non_retryable_errors())
            assert error_message_matches(str(error.value), ConvexSource().get_retryable_errors())
            assert not scoped.can_resume()
            assert inputs.source_cursor is not None and inputs.source_cursor.staged is None
            inputs.source_cursor = SourceCursorManager(ConvexDataSyncCursor, None, ConvexSource())
            inputs.db_incremental_field_last_value = None
            inputs.reset_pipeline = True
            http_boundary.post.side_effect = None
            http_boundary.post.return_value = _page("rebuilt", truncates=[{"component": "auth", "table": "users"}])
            list(_items(_resource(inputs, manager)))
            assert "cursor" not in http_boundary.post.call_args.kwargs["json"]
        else:
            assert list(_items(_resource(inputs, manager))) == [[{"_id": "replacement", "_ts": 999, "_deleted": False}]]
            reset.assert_not_called()


def _pipeline_safe_point(manager: Any) -> Any:
    def hook() -> None:
        manager.confirm()
        manager.commit()

    return hook


@pytest.mark.parametrize("rows", [[], [{"value": {"_id": "a"}, "ts": 100, "deleted": False}]])
def test_each_page_saves_resume_state_after_rows_and_continues_on_retry(
    rows: list[dict[str, Any]], redis_boundary: Mock, http_boundary: Mock
) -> None:
    inputs = _inputs(stored="stored")
    manager = ConvexSource().get_resumable_source_manager(inputs)
    scoped = manager.with_namespace("data_sync")
    http_boundary.post.side_effect = [_page("checkpoint", status="stale", values=rows), RuntimeError("interrupted")]
    with activate_safe_point(_pipeline_safe_point(manager), covers_framework_checkpoints=False):
        iterator = iter(_items(_resource(inputs, manager)))
        if rows:
            assert next(iterator) == [{"_id": "a", "_ts": 100, "_deleted": False}]
            assert not scoped.can_resume()
        with pytest.raises(RuntimeError, match="interrupted"):
            list(iterator)
    assert scoped.load_state() == ConvexResumeConfig(cursor="checkpoint", started_from_cursor=True)
    http_boundary.post.side_effect = None
    http_boundary.post.return_value = _page("end")
    retry_manager = ConvexSource().get_resumable_source_manager(inputs)
    with activate_safe_point(_pipeline_safe_point(retry_manager), covers_framework_checkpoints=False):
        list(_items(_resource(inputs, retry_manager)))
    assert http_boundary.post.call_args.kwargs["json"]["cursor"] == "checkpoint"
    assert scoped.load_state() == ConvexResumeConfig(cursor="end", started_from_cursor=True)
    assert inputs.source_cursor is not None and inputs.source_cursor.staged == ConvexDataSyncCursor(cursor="end")


def test_data_sync_plan_error_maps_to_professional_plan(redis_boundary: Mock, http_boundary: Mock) -> None:
    inputs = _inputs()
    http_boundary.post.return_value = _make_response({"code": "StreamingExportNotEnabled"}, status_code=400)
    with pytest.raises(StreamingExportNotEnabledError) as error:
        list(_items(_resource(inputs, ConvexSource().get_resumable_source_manager(inputs))))
    matches = [message for key, message in ConvexSource().get_non_retryable_errors().items() if key in str(error.value)]
    assert matches and matches[0] is not None and "requires the Convex Professional plan" in matches[0]
