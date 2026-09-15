from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_monitoring.gcp_cloud_monitoring import (
    TOKEN_URI,
    GcpCloudMonitoringClient,
    GcpCloudMonitoringError,
    GcpCloudMonitoringResumeConfig,
    TimeWindow,
    _time_windows,
    build_time_series_params,
    flatten_time_series,
    gcp_cloud_monitoring_source,
    make_authed_session,
    resolve_start_time,
    series_key,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_monitoring.settings import (
    INITIAL_BACKFILL_DAYS,
    WINDOW_HOURS,
)

FILTER = 'resource.type="consumed_api" AND metric.type="serviceruntime.googleapis.com/api/request_count"'
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _manager(resume_state: GcpCloudMonitoringResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _series(metric_labels: dict[str, str], points: list[tuple[str, Any]]) -> dict[str, Any]:
    return {
        "metric": {"type": "serviceruntime.googleapis.com/api/request_count", "labels": metric_labels},
        "resource": {"type": "consumed_api", "labels": {"service": "places.googleapis.com"}},
        "metricKind": "DELTA",
        "valueType": "INT64",
        "points": [
            {"interval": {"startTime": end, "endTime": end}, "value": {"int64Value": value}} for end, value in points
        ],
    }


class TestTimeWindows:
    def test_splits_range_into_bounded_windows(self):
        windows = list(_time_windows(NOW - timedelta(hours=48), NOW, 24))
        assert len(windows) == 2
        assert windows[0].end == windows[1].start

    def test_final_window_is_clipped_to_the_end(self):
        start = NOW - timedelta(hours=5)
        assert list(_time_windows(start, NOW, 24)) == [TimeWindow(start=start, end=NOW)]

    def test_empty_when_start_is_not_before_end(self):
        assert list(_time_windows(NOW, NOW, 24)) == []


class TestResolveStartTime:
    def test_no_cursor_falls_back_to_the_retention_window(self):
        assert (NOW - resolve_start_time(None, NOW)).days == INITIAL_BACKFILL_DAYS

    @pytest.mark.parametrize("cursor", ["2026-08-01T00:00:00Z", "2026-08-01T00:00:00+00:00"])
    def test_parses_the_timestamp_shapes_the_api_returns(self, cursor: str):
        assert resolve_start_time(cursor, NOW) == datetime(2026, 8, 1, tzinfo=UTC)

    def test_naive_cursor_is_read_as_utc_rather_than_local_time(self):
        assert resolve_start_time("2026-08-01T00:00:00", NOW).tzinfo == UTC


class TestSeriesKey:
    def test_same_series_yields_the_same_key_regardless_of_label_order(self):
        first = series_key({"type": "m", "labels": {"a": "1", "b": "2"}}, {"type": "r", "labels": {}})
        second = series_key({"type": "m", "labels": {"b": "2", "a": "1"}}, {"type": "r", "labels": {}})
        assert first == second

    def test_a_differing_label_value_splits_the_key(self):
        first = series_key({"type": "m", "labels": {"a": "1"}}, {"type": "r", "labels": {}})
        second = series_key({"type": "m", "labels": {"a": "2"}}, {"type": "r", "labels": {}})
        assert first != second

    def test_resource_labels_split_the_key_too(self):
        first = series_key({"type": "m", "labels": {}}, {"type": "r", "labels": {"service": "a"}})
        second = series_key({"type": "m", "labels": {}}, {"type": "r", "labels": {"service": "b"}})
        assert first != second


class TestFlattenTimeSeries:
    def test_one_row_per_point_carrying_the_series_labels(self):
        rows = flatten_time_series(
            [_series({"response_code": "200"}, [("2026-08-13T10:00:00Z", "5"), ("2026-08-13T09:00:00Z", "3")])]
        )
        assert len(rows) == 2
        assert {row["metric_labels"]["response_code"] for row in rows} == {"200"}
        assert rows[0]["resource_labels"]["service"] == "places.googleapis.com"

    def test_points_from_different_series_get_different_keys(self):
        rows = flatten_time_series(
            [
                _series({"response_code": "200"}, [("2026-08-13T10:00:00Z", "5")]),
                _series({"response_code": "500"}, [("2026-08-13T10:00:00Z", "1")]),
            ]
        )
        assert rows[0]["series_key"] != rows[1]["series_key"]

    def test_every_value_column_is_present_so_the_schema_does_not_shift(self):
        rows = flatten_time_series([_series({}, [("2026-08-13T10:00:00Z", "5")])])
        assert rows[0]["int64Value"] == "5"
        for absent in ("doubleValue", "boolValue", "stringValue", "distributionValue"):
            assert rows[0][absent] is None

    def test_a_series_with_no_points_yields_no_rows(self):
        assert flatten_time_series([_series({}, [])]) == []

    def test_missing_metric_and_resource_blocks_do_not_raise(self):
        assert (
            flatten_time_series([{"points": [{"interval": {"endTime": "x"}, "value": {}}]}])[0]["metric_type"] is None
        )


class TestMakeAuthedSession:
    def test_tokens_are_minted_against_googles_fixed_endpoint(self):
        with patch("google.oauth2.service_account.Credentials.from_service_account_info") as from_info:
            make_authed_session(project_id="p", private_key="pk", private_key_id="pkid", client_email="sa@example.com")
        assert from_info.call_args.args[0]["token_uri"] == TOKEN_URI


class TestBuildTimeSeriesParams:
    def _params(self, **overrides):
        return build_time_series_params(
            FILTER,
            NOW - timedelta(hours=1),
            NOW,
            overrides.get("alignment_period_seconds"),
            overrides.get("per_series_aligner"),
            overrides.get("cross_series_reducer"),
            overrides.get("group_by_fields"),
        )

    def test_sends_the_filter_and_an_rfc3339_interval(self):
        params = self._params()
        assert params["filter"] == FILTER
        assert params["interval.startTime"] == "2026-08-13T11:00:00Z"
        assert params["interval.endTime"] == "2026-08-13T12:00:00Z"
        assert params["view"] == "FULL"

    def test_aggregation_stays_off_by_default(self):
        assert not [key for key in self._params() if key.startswith("aggregation.")]

    def test_an_aligner_always_travels_with_an_alignment_period(self):
        params = self._params(per_series_aligner="ALIGN_SUM")
        assert params["aggregation.perSeriesAligner"] == "ALIGN_SUM"
        assert params["aggregation.alignmentPeriod"] == "3600s"

    def test_a_configured_alignment_period_is_used(self):
        params = self._params(per_series_aligner="ALIGN_SUM", alignment_period_seconds=300)
        assert params["aggregation.alignmentPeriod"] == "300s"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"cross_series_reducer": "REDUCE_SUM"},
            {"group_by_fields": ["resource.labels.service"]},
            {"alignment_period_seconds": 300},
            {"per_series_aligner": "ALIGN_SUM", "group_by_fields": ["resource.labels.service"]},
        ],
    )
    def test_an_aggregation_setting_that_would_be_dropped_is_refused(self, overrides):
        with pytest.raises(GcpCloudMonitoringError):
            self._params(**overrides)

    def test_group_by_fields_ride_with_the_reducer(self):
        params = self._params(
            per_series_aligner="ALIGN_SUM",
            cross_series_reducer="REDUCE_SUM",
            group_by_fields=["resource.labels.service"],
        )
        assert params["aggregation.groupByFields"] == ["resource.labels.service"]


class TestClientPagination:
    def _session(self, pages: list[dict[str, Any]]) -> MagicMock:
        session = MagicMock()
        responses = []
        for page in pages:
            response = MagicMock()
            response.json.return_value = page
            responses.append(response)
        session.get.side_effect = responses
        return session

    def test_follows_next_page_token_until_it_is_absent(self):
        session = self._session(
            [
                {"metricDescriptors": [{"name": "a"}], "nextPageToken": "t1"},
                {"metricDescriptors": [{"name": "b"}]},
            ]
        )
        client = GcpCloudMonitoringClient(session, "proj")

        batches = list(client.list_metric_descriptors())

        assert batches == [[{"name": "a"}], [{"name": "b"}]]
        assert session.get.call_args_list[1].kwargs["params"]["pageToken"] == "t1"

    def test_an_empty_next_page_token_ends_pagination(self):
        session = self._session([{"metricDescriptors": [{"name": "a"}], "nextPageToken": ""}])
        assert list(GcpCloudMonitoringClient(session, "proj").list_metric_descriptors()) == [[{"name": "a"}]]

    def test_resource_descriptors_read_their_own_collection_key(self):
        session = self._session([{"resourceDescriptors": [{"name": "r"}]}])
        assert list(GcpCloudMonitoringClient(session, "proj").list_monitored_resource_descriptors()) == [
            [{"name": "r"}]
        ]

    def test_a_page_with_no_items_is_not_yielded(self):
        session = self._session([{"nextPageToken": "t1"}, {"metricDescriptors": [{"name": "a"}]}])
        assert list(GcpCloudMonitoringClient(session, "proj").list_metric_descriptors()) == [[{"name": "a"}]]


class TestGcpCloudMonitoringSource:
    def _client(self, pages: list[list[dict[str, Any]]] | None = None) -> MagicMock:
        client = MagicMock()
        client.list_time_series.return_value = iter(pages if pages is not None else [])
        return client

    def test_descriptor_tables_bypass_the_time_series_path(self):
        client = self._client()
        client.list_metric_descriptors.return_value = iter([[{"name": "a"}]])

        batches = list(gcp_cloud_monitoring_source(client, "MetricDescriptors", _manager(), FILTER, now=NOW))

        assert batches == [[{"name": "a"}]]
        client.list_time_series.assert_not_called()

    def test_time_series_without_a_filter_fails_with_an_actionable_message(self):
        with pytest.raises(GcpCloudMonitoringError, match="needs a monitoring filter"):
            list(gcp_cloud_monitoring_source(self._client(), "TimeSeries", _manager(), "", now=NOW))

    def test_unknown_table_is_rejected(self):
        with pytest.raises(GcpCloudMonitoringError, match="Unknown Cloud Monitoring table"):
            list(gcp_cloud_monitoring_source(self._client(), "Nope", _manager(), FILTER, now=NOW))

    def test_window_rows_are_sorted_ascending_because_the_api_returns_newest_first(self):
        client = self._client([[_series({}, [("2026-08-13T11:00:00Z", "2"), ("2026-08-13T10:00:00Z", "1")])]])
        batches = list(
            gcp_cloud_monitoring_source(client, "TimeSeries", _manager(), FILTER, "2026-08-13T09:00:00Z", now=NOW)
        )
        assert [row["point_end_time"] for row in batches[0]] == [
            "2026-08-13T10:00:00Z",
            "2026-08-13T11:00:00Z",
        ]

    def test_rows_from_several_pages_are_sorted_together(self):
        client = MagicMock()
        client.list_time_series.return_value = iter(
            [
                [_series({"a": "1"}, [("2026-08-13T11:00:00Z", "2")])],
                [_series({"a": "2"}, [("2026-08-13T10:00:00Z", "1")])],
            ]
        )
        batches = list(
            gcp_cloud_monitoring_source(client, "TimeSeries", _manager(), FILTER, "2026-08-13T09:00:00Z", now=NOW)
        )
        assert [row["point_end_time"] for row in batches[0]] == [
            "2026-08-13T10:00:00Z",
            "2026-08-13T11:00:00Z",
        ]

    def test_incremental_cursor_sets_the_first_window_start(self):
        client = self._client()
        list(gcp_cloud_monitoring_source(client, "TimeSeries", _manager(), FILTER, "2026-08-13T09:00:00Z", now=NOW))
        assert client.list_time_series.call_args_list[0].args[0]["interval.startTime"] == ("2026-08-13T09:00:00Z")

    def test_saved_resume_state_wins_over_the_incremental_cursor(self):
        client = self._client()
        manager = _manager(GcpCloudMonitoringResumeConfig(next_start_time="2026-08-13T11:00:00Z"))

        list(gcp_cloud_monitoring_source(client, "TimeSeries", manager, FILTER, "2026-08-01T00:00:00Z", now=NOW))

        assert client.list_time_series.call_args_list[0].args[0]["interval.startTime"] == ("2026-08-13T11:00:00Z")

    def test_state_advances_to_the_end_of_every_window_even_when_empty(self):
        client = self._client()
        manager = _manager()

        batches = list(
            gcp_cloud_monitoring_source(client, "TimeSeries", manager, FILTER, "2026-08-11T12:00:00Z", now=NOW)
        )

        assert batches == []
        saved = [call.args[0].next_start_time for call in manager.save_state.call_args_list]
        assert saved[-1] == "2026-08-13T12:00:00Z"

    def test_long_backfill_is_split_into_bounded_windows(self):
        client = self._client()
        list(gcp_cloud_monitoring_source(client, "TimeSeries", _manager(), FILTER, "2026-08-01T12:00:00Z", now=NOW))
        for call in client.list_time_series.call_args_list:
            params = call.args[0]
            start = datetime.fromisoformat(params["interval.startTime"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(params["interval.endTime"].replace("Z", "+00:00"))
            assert (end - start) <= timedelta(hours=WINDOW_HOURS)


class TestValidateCredentials:
    def _session(self, status_code: int) -> MagicMock:
        session = MagicMock()
        response = MagicMock()
        response.status_code = status_code
        session.get.return_value = response
        return session

    def test_a_readable_project_validates(self):
        assert validate_credentials(self._session(200), "proj") == (True, None)

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_a_denied_key_names_the_role_to_grant(self, status_code: int):
        ok, message = validate_credentials(self._session(status_code), "proj")
        assert ok is False
        assert message is not None and "Monitoring Viewer" in message

    def test_a_missing_project_is_reported_as_such(self):
        ok, message = validate_credentials(self._session(404), "proj")
        assert ok is False
        assert message is not None and "was not found" in message

    def test_a_transport_failure_does_not_escape(self):
        session = MagicMock()
        session.get.side_effect = OSError("boom")
        ok, message = validate_credentials(session, "proj")
        assert ok is False
        assert message is not None
