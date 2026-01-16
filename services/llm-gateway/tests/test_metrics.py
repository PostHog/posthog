import pytest
from prometheus_client import generate_latest

from llm_gateway.metrics.prometheus import (
    ACTIVE_STREAMS,
    CALLBACK_ERRORS,
    CALLBACK_SUCCESS,
    CONCURRENT_REQUESTS,
    DB_POOL_SIZE,
    PROVIDER_ERRORS,
    PROVIDER_LATENCY,
    RATE_LIMIT_EXCEEDED,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    STREAMING_CLIENT_DISCONNECT,
    TIME_TO_FIRST_CHUNK,
    TOKENS_INPUT,
    TOKENS_OUTPUT,
)


class TestMetricsConfiguration:
    @pytest.mark.parametrize(
        "metric,expected_labels",
        [
            pytest.param(
                REQUEST_COUNT,
                {"endpoint", "provider", "model", "status_code", "auth_method", "product"},
                id="request_count",
            ),
            pytest.param(REQUEST_LATENCY, {"endpoint", "provider", "streaming", "product"}, id="request_latency"),
            pytest.param(TOKENS_INPUT, {"provider", "model", "product"}, id="tokens_input"),
            pytest.param(TOKENS_OUTPUT, {"provider", "model", "product"}, id="tokens_output"),
            pytest.param(RATE_LIMIT_EXCEEDED, {"scope"}, id="rate_limit_exceeded"),
            pytest.param(PROVIDER_ERRORS, {"provider", "error_type", "product"}, id="provider_errors"),
            pytest.param(ACTIVE_STREAMS, {"provider", "model", "product"}, id="active_streams"),
            pytest.param(CONCURRENT_REQUESTS, {"provider", "model", "product"}, id="concurrent_requests"),
            pytest.param(
                STREAMING_CLIENT_DISCONNECT, {"provider", "model", "product"}, id="streaming_client_disconnect"
            ),
            pytest.param(TIME_TO_FIRST_CHUNK, {"provider", "model", "product"}, id="time_to_first_chunk"),
            pytest.param(DB_POOL_SIZE, {"state"}, id="db_pool_size"),
            pytest.param(PROVIDER_LATENCY, {"provider", "model", "product"}, id="provider_latency"),
            pytest.param(CALLBACK_SUCCESS, {"callback"}, id="callback_success"),
            pytest.param(CALLBACK_ERRORS, {"callback", "error_type"}, id="callback_errors"),
        ],
    )
    def test_metric_has_correct_labels(self, metric, expected_labels: set[str]) -> None:
        assert set(metric._labelnames) == expected_labels

    def test_rate_limit_excluded_high_cardinality_labels(self) -> None:
        high_cardinality = {"user_id", "team_id", "request_id"}
        assert high_cardinality.isdisjoint(RATE_LIMIT_EXCEEDED._labelnames)


class TestMetricsExport:
    def test_metrics_can_be_exported_to_prometheus_format(self) -> None:
        output = generate_latest()
        assert b"llm_gateway" in output

    @pytest.mark.parametrize(
        "metric_name",
        [
            pytest.param(b"llm_gateway_requests_total", id="request_count"),
            pytest.param(b"llm_gateway_request_duration_seconds", id="request_latency"),
            pytest.param(b"llm_gateway_tokens_input_total", id="tokens_input"),
            pytest.param(b"llm_gateway_tokens_output_total", id="tokens_output"),
            pytest.param(b"llm_gateway_rate_limit_exceeded_total", id="rate_limit"),
            pytest.param(b"llm_gateway_provider_errors_total", id="provider_errors"),
            pytest.param(b"llm_gateway_active_streams", id="active_streams"),
            pytest.param(b"llm_gateway_concurrent_requests", id="concurrent_requests"),
            pytest.param(b"llm_gateway_streaming_client_disconnect_total", id="streaming_client_disconnect"),
            pytest.param(b"llm_gateway_db_pool_size", id="db_pool_size"),
            pytest.param(b"llm_gateway_provider_latency_seconds", id="provider_latency"),
        ],
    )
    def test_metric_appears_in_prometheus_output(self, metric_name: bytes) -> None:
        output = generate_latest()
        assert metric_name in output


class TestMetricsRecording:
    def test_rate_limit_exceeded_increments_without_user_id(self) -> None:
        initial_value = RATE_LIMIT_EXCEEDED.labels(scope="burst")._value.get()
        RATE_LIMIT_EXCEEDED.labels(scope="burst").inc()
        assert RATE_LIMIT_EXCEEDED.labels(scope="burst")._value.get() == initial_value + 1

    def test_provider_errors_tracks_error_types(self) -> None:
        initial_value = PROVIDER_ERRORS.labels(
            provider="anthropic", error_type="TimeoutError", product="llm_gateway"
        )._value.get()
        PROVIDER_ERRORS.labels(provider="anthropic", error_type="TimeoutError", product="llm_gateway").inc()
        assert (
            PROVIDER_ERRORS.labels(provider="anthropic", error_type="TimeoutError", product="llm_gateway")._value.get()
            == initial_value + 1
        )

    def test_active_streams_can_increment_and_decrement(self) -> None:
        ACTIVE_STREAMS.labels(provider="openai", model="gpt-4", product="llm_gateway").set(0)
        ACTIVE_STREAMS.labels(provider="openai", model="gpt-4", product="llm_gateway").inc()
        assert ACTIVE_STREAMS.labels(provider="openai", model="gpt-4", product="llm_gateway")._value.get() == 1
        ACTIVE_STREAMS.labels(provider="openai", model="gpt-4", product="llm_gateway").dec()
        assert ACTIVE_STREAMS.labels(provider="openai", model="gpt-4", product="llm_gateway")._value.get() == 0

    def test_concurrent_requests_can_increment_and_decrement(self) -> None:
        CONCURRENT_REQUESTS.labels(provider="anthropic", model="claude-3", product="llm_gateway").set(0)
        CONCURRENT_REQUESTS.labels(provider="anthropic", model="claude-3", product="llm_gateway").inc()
        assert (
            CONCURRENT_REQUESTS.labels(provider="anthropic", model="claude-3", product="llm_gateway")._value.get() == 1
        )
        CONCURRENT_REQUESTS.labels(provider="anthropic", model="claude-3", product="llm_gateway").dec()
        assert (
            CONCURRENT_REQUESTS.labels(provider="anthropic", model="claude-3", product="llm_gateway")._value.get() == 0
        )

    def test_streaming_client_disconnect_increments(self) -> None:
        initial = STREAMING_CLIENT_DISCONNECT.labels(
            provider="openai", model="gpt-4", product="llm_gateway"
        )._value.get()
        STREAMING_CLIENT_DISCONNECT.labels(provider="openai", model="gpt-4", product="llm_gateway").inc()
        assert (
            STREAMING_CLIENT_DISCONNECT.labels(provider="openai", model="gpt-4", product="llm_gateway")._value.get()
            == initial + 1
        )

    def test_db_pool_size_tracks_connection_states(self) -> None:
        DB_POOL_SIZE.labels(state="idle").set(5)
        DB_POOL_SIZE.labels(state="active").set(3)
        assert DB_POOL_SIZE.labels(state="idle")._value.get() == 5
        assert DB_POOL_SIZE.labels(state="active")._value.get() == 3

    def test_tokens_counter_accepts_large_values(self) -> None:
        initial = TOKENS_INPUT.labels(provider="anthropic", model="claude-3", product="llm_gateway")._value.get()
        TOKENS_INPUT.labels(provider="anthropic", model="claude-3", product="llm_gateway").inc(100000)
        assert (
            TOKENS_INPUT.labels(provider="anthropic", model="claude-3", product="llm_gateway")._value.get()
            == initial + 100000
        )

    def test_request_latency_histogram_observes_values(self) -> None:
        REQUEST_LATENCY.labels(endpoint="test", provider="test", streaming="false", product="llm_gateway").observe(0.5)
        REQUEST_LATENCY.labels(endpoint="test", provider="test", streaming="false", product="llm_gateway").observe(1.5)

    def test_provider_latency_histogram_observes_values(self) -> None:
        PROVIDER_LATENCY.labels(provider="anthropic", model="claude-3", product="llm_gateway").observe(0.25)
        PROVIDER_LATENCY.labels(provider="anthropic", model="claude-3", product="llm_gateway").observe(2.5)

    def test_time_to_first_chunk_histogram_observes_values(self) -> None:
        TIME_TO_FIRST_CHUNK.labels(provider="anthropic", model="claude-3", product="llm_gateway").observe(0.15)
        TIME_TO_FIRST_CHUNK.labels(provider="anthropic", model="claude-3", product="llm_gateway").observe(0.75)

    def test_callback_success_increments(self) -> None:
        initial = CALLBACK_SUCCESS.labels(callback="test_callback")._value.get()
        CALLBACK_SUCCESS.labels(callback="test_callback").inc()
        assert CALLBACK_SUCCESS.labels(callback="test_callback")._value.get() == initial + 1

    def test_callback_errors_tracks_error_types(self) -> None:
        initial = CALLBACK_ERRORS.labels(callback="test_callback", error_type="ValueError")._value.get()
        CALLBACK_ERRORS.labels(callback="test_callback", error_type="ValueError").inc()
        assert CALLBACK_ERRORS.labels(callback="test_callback", error_type="ValueError")._value.get() == initial + 1
