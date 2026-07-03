from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex import (
    _CONVEX_RETRY,
    ConvexResumeConfig,
    InvalidDeployUrlError,
    InvalidWindowError,
    convex_source,
    document_deltas,
    list_snapshot,
    validate_credentials,
    validate_deploy_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.convex.source import ConvexSource


def _make_response(json_data: dict[str, Any], status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    response.raise_for_status = Mock()
    return response


def _make_manager(can_resume: bool = False, state: ConvexResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    # Endpoint scoping returns a sibling manager; resolve it back to this mock so call
    # assertions still observe the same object.
    manager.with_namespace.return_value = manager
    return manager


class TestValidateDeployUrl:
    @parameterized.expand(
        [
            # valid — should normalize to clean https://host
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
            # missing scheme — normalized by prepending https://
            ("no_scheme", "swift-lemur-123.convex.cloud", "https://swift-lemur-123.convex.cloud"),
            (
                "no_scheme_regional",
                "breezy-otter-42.eu-west-1.convex.cloud",
                "https://breezy-otter-42.eu-west-1.convex.cloud",
            ),
            ("no_scheme_trailing_slash", "swift-lemur-123.convex.cloud/", "https://swift-lemur-123.convex.cloud"),
            # invalid — should raise
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

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_validate_credentials_rejects_bad_url_without_network_call(self, mock_get):
        ok, err = validate_credentials("http://169.254.169.254", "deploy-key")
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


class TestListSnapshotResumable:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_fresh_run_saves_state_after_each_page(self, mock_get: Mock) -> None:
        manager = _make_manager(can_resume=False)
        mock_get.return_value.get.side_effect = [
            _make_response({"values": [{"_id": "a"}], "cursor": 100, "snapshot": 500, "hasMore": True}),
            _make_response({"values": [{"_id": "b"}], "cursor": 200, "snapshot": 500, "hasMore": True}),
            _make_response({"values": [{"_id": "c"}], "cursor": 300, "snapshot": 500, "hasMore": False}),
        ]

        gen = list_snapshot("https://x.convex.cloud", "key", "t", manager)
        batches = list(gen)

        assert batches == [[{"_id": "a"}], [{"_id": "b"}], [{"_id": "c"}]]
        manager.can_resume.assert_called_once()
        manager.load_state.assert_not_called()

        # State saved after each non-terminal page points to the NEXT page's cursor/snapshot.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            ConvexResumeConfig(cursor=100, snapshot=500),
            ConvexResumeConfig(cursor=200, snapshot=500),
        ]

        # First request has no cursor/snapshot params; subsequent requests use the saved values.
        first_params = mock_get.return_value.get.call_args_list[0].kwargs["params"]
        assert "cursor" not in first_params
        assert "snapshot" not in first_params
        second_params = mock_get.return_value.get.call_args_list[1].kwargs["params"]
        assert second_params["cursor"] == 100
        assert second_params["snapshot"] == 500

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_resume_seeds_paginator_from_saved_state(self, mock_get: Mock) -> None:
        saved = ConvexResumeConfig(cursor=200, snapshot=500)
        manager = _make_manager(can_resume=True, state=saved)
        mock_get.return_value.get.return_value = _make_response(
            {"values": [{"_id": "b"}], "cursor": 300, "snapshot": 500, "hasMore": False}
        )

        batches = list(list_snapshot("https://x.convex.cloud", "key", "t", manager))

        assert batches == [[{"_id": "b"}]]
        manager.load_state.assert_called_once()
        # Paginator must start from saved cursor/snapshot, not from scratch.
        first_params = mock_get.return_value.get.call_args_list[0].kwargs["params"]
        assert first_params["cursor"] == 200
        assert first_params["snapshot"] == 500
        # Final page terminates the loop before any save_state.
        manager.save_state.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_empty_final_page_does_not_save_state(self, mock_get: Mock) -> None:
        manager = _make_manager(can_resume=False)
        mock_get.return_value.get.return_value = _make_response({"values": [], "snapshot": 0, "hasMore": False})

        batches = list(list_snapshot("https://x.convex.cloud", "key", "t", manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestDocumentDeltasResumable:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_fresh_run_saves_state_after_each_page(self, mock_get: Mock) -> None:
        manager = _make_manager(can_resume=False)
        mock_get.return_value.get.side_effect = [
            _make_response({"values": [{"_id": "a"}], "cursor": 20, "hasMore": True}),
            _make_response({"values": [{"_id": "b"}], "cursor": 30, "hasMore": False}),
        ]

        batches = list(document_deltas("https://x.convex.cloud", "key", "t", 10, manager))

        assert batches == [[{"_id": "a"}], [{"_id": "b"}]]
        manager.can_resume.assert_called_once()
        manager.load_state.assert_not_called()
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ConvexResumeConfig(cursor=20)]

        # First request starts from the provided db cursor.
        first_params = mock_get.return_value.get.call_args_list[0].kwargs["params"]
        assert first_params["cursor"] == 10

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_session_uses_convex_retry_policy(self, mock_get: Mock) -> None:
        manager = _make_manager(can_resume=False)
        mock_get.return_value.get.return_value = _make_response({"values": [], "cursor": 10, "hasMore": False})

        list(document_deltas("https://x.convex.cloud", "key", "t", 10, manager))

        # The Cloudflare-aware retry policy must be wired into the HTTP session, otherwise a
        # transient 520 is raised immediately instead of retried.
        assert mock_get.call_args.kwargs["retry"] is _CONVEX_RETRY

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_resume_overrides_db_cursor(self, mock_get: Mock) -> None:
        saved = ConvexResumeConfig(cursor=25)
        manager = _make_manager(can_resume=True, state=saved)
        mock_get.return_value.get.return_value = _make_response(
            {"values": [{"_id": "b"}], "cursor": 30, "hasMore": False}
        )

        batches = list(document_deltas("https://x.convex.cloud", "key", "t", 10, manager))

        assert batches == [[{"_id": "b"}]]
        # Resume state wins over the db_incremental_field_last_value seed.
        first_params = mock_get.return_value.get.call_args_list[0].kwargs["params"]
        assert first_params["cursor"] == 25
        manager.save_state.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_non_integer_resume_cursor_is_ignored(self, mock_get: Mock) -> None:
        # A list_snapshot resume cursor ({tablet, id}) leaking into document_deltas must not be
        # replayed — document_deltas requires an integer _ts and Convex 400s on the malformed
        # cursor. Fall back to the db watermark instead.
        saved = ConvexResumeConfig(cursor='{"tablet":"-cxKinhlnLuQp","id":"v9769ybsnjbhc9"}')
        manager = _make_manager(can_resume=True, state=saved)
        mock_get.return_value.get.return_value = _make_response(
            {"values": [{"_id": "b"}], "cursor": 30, "hasMore": False}
        )

        batches = list(document_deltas("https://x.convex.cloud", "key", "t", 10, manager))

        assert batches == [[{"_id": "b"}]]
        first_params = mock_get.return_value.get.call_args_list[0].kwargs["params"]
        assert first_params["cursor"] == 10
        # Discarding a poisoned cursor must not persist new state off the back of it.
        manager.save_state.assert_not_called()


class TestConvexRetryPolicy:
    @parameterized.expand(
        [
            # Cloudflare 52x family — Convex sits behind Cloudflare and emits these on transient
            # edge/origin trouble. The 520 here is the exact code that fails syncs in production.
            ("cf_520_unknown_error", 520, True),
            ("cf_521_web_server_down", 521, True),
            ("cf_522_connection_timed_out", 522, True),
            ("cf_523_origin_unreachable", 523, True),
            ("cf_524_timeout", 524, True),
            # Standard transient codes inherited from DEFAULT_RETRY must still be retried.
            ("rate_limited_429", 429, True),
            ("internal_500", 500, True),
            ("bad_gateway_502", 502, True),
            ("service_unavailable_503", 503, True),
            ("gateway_timeout_504", 504, True),
            # Client errors are not transient — they must not be retried away.
            ("bad_request_400", 400, False),
            ("unauthorized_401", 401, False),
            ("forbidden_403", 403, False),
            ("not_found_404", 404, False),
        ]
    )
    def test_retry_status_handling(self, _name: str, status_code: int, expected_retry: bool) -> None:
        assert _CONVEX_RETRY.is_retry("GET", status_code) is expected_retry


class TestConvexSource:
    @parameterized.expand(
        [
            (
                "full_refresh",
                False,
                None,
                {"values": [{"_id": "a", "_creationTime": 1}], "cursor": 100, "snapshot": 500, "hasMore": False},
                [[{"_id": "a", "_creationTime": 1}]],
                "/api/list_snapshot",
                {},
            ),
            (
                "incremental",
                True,
                10,
                {"values": [{"_id": "a"}], "cursor": 50, "hasMore": False},
                [[{"_id": "a"}]],
                "/api/document_deltas",
                {"cursor": 10},
            ),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_threads_manager(
        self,
        _name: str,
        should_use_incremental_field: bool,
        db_incremental_field_last_value: int | None,
        response_json: dict[str, Any],
        expected_batches: list[list[dict[str, Any]]],
        expected_url_fragment: str,
        expected_first_params: dict[str, Any],
        mock_get: Mock,
    ) -> None:
        manager = _make_manager(can_resume=False)
        mock_get.return_value.get.return_value = _make_response(response_json)

        response = convex_source(
            deploy_url="https://x.convex.cloud",
            deploy_key="key",
            table_name="t",
            team_id=1,
            job_id="job",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            resumable_source_manager=manager,
        )

        batches = list(cast(Iterable[Any], response.items()))
        assert batches == expected_batches
        assert response.primary_keys == ["_id"]
        manager.can_resume.assert_called_once()
        called_url = mock_get.return_value.get.call_args_list[0].args[0]
        assert expected_url_fragment in called_url
        first_params = mock_get.return_value.get.call_args_list[0].kwargs["params"]
        for key, value in expected_first_params.items():
            assert first_params[key] == value


class TestConvexNonRetryableErrors:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.convex.convex.make_tracked_session")
    def test_invalid_window_message_is_recognised_as_non_retryable(self, mock_get: Mock) -> None:
        # The activity-level non-retryable check compares its keys against `str(exception)`, which is
        # the message only — not the class name. Drive document_deltas to raise the real error and
        # assert the produced message matches a configured non-retryable key.
        manager = _make_manager(can_resume=False)
        mock_get.return_value.get.return_value = _make_response(
            {
                "code": "InvalidWindowToReadDocuments",
                "message": "Trying to synchronize from a timestamp older than the retention window.",
            },
            status_code=400,
        )

        with pytest.raises(InvalidWindowError) as exc_info:
            list(document_deltas("https://x.convex.cloud", "key", "email_unsubscribes", 10, manager))

        error_msg = str(exc_info.value)
        non_retryable_errors = ConvexSource().get_non_retryable_errors()
        assert any(key in error_msg for key in non_retryable_errors), error_msg

    @parameterized.expand(
        [
            ("401", "401 Client Error: Unauthorized for url: https://x.convex.cloud/api/document_deltas"),
            ("403", "403 Client Error: Forbidden for url: https://x.convex.cloud/api/document_deltas"),
            (
                "invalid_window",
                "Delta cursor for table 'events' is older than Convex's ~30 day retention window. "
                "Please trigger a full resync of this source.",
            ),
        ]
    )
    def test_known_errors_match(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = ConvexSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error for url: https://x.convex.cloud/api/document_deltas"),
            ("read_timeout", "HTTPSConnectionPool(host='x.convex.cloud', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_do_not_match(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = ConvexSource().get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable_errors)
