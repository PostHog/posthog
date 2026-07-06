import json

import pytest
from unittest.mock import MagicMock, patch

from google.protobuf.struct_pb2 import Struct

from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc import sampling
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.observer import GrpcRequestRecord
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.proto_utils import (
    message_byte_size,
    message_to_scrubbed_dict,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling import (
    CAPTURE_CONFIG_REDIS_KEY,
    S3_PREFIX,
    _build_sample_payload,
    _first_match,
    _matches_grpc_status,
    maybe_capture,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import JobContext
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sample_scrub import (
    CaptureConfig,
    CaptureRule,
)


@pytest.fixture(autouse=True)
def _reset_caches():
    sampling._reset_cache_for_tests()
    yield
    sampling._reset_cache_for_tests()


def _ctx(team_id: int = 99, source_type: str = "google_ads", schema_id: str = "schema-uuid") -> JobContext:
    return JobContext(
        team_id=team_id,
        source_type=source_type,
        external_data_source_id="src-uuid",
        external_data_schema_id=schema_id,
        external_data_job_id="run-id",
    )


def _record(
    *,
    method: str = "/svc/Search",
    status_class: str = "ok",
    status_code_num: int | None = 0,
    message_count: int | None = 1,
) -> GrpcRequestRecord:
    return GrpcRequestRecord(
        method=method,
        host="googleads.googleapis.com",
        request_bytes=10,
        response_bytes=20,
        status_class=status_class,
        status_code_num=status_code_num,
        latency_ms=42,
        message_count=message_count,
        error_class=None,
    )


def _struct(data: dict) -> Struct:
    s = Struct()
    s.update(data)
    return s


# ---------------------------------------------------------------------------
# proto helpers
# ---------------------------------------------------------------------------


def test_message_byte_size_of_proto():
    msg = _struct({"a": "b"})
    assert message_byte_size(msg) == msg.ByteSize()
    assert message_byte_size(msg) > 0


def test_message_byte_size_of_non_message_is_zero():
    assert message_byte_size(object()) == 0
    assert message_byte_size(None) == 0
    assert message_byte_size({"not": "a message"}) == 0


def test_message_to_scrubbed_dict_redacts_auth_keys():
    msg = _struct({"developer_token": "super-secret", "refresh_token": "rt", "name": "campaign"})
    result = message_to_scrubbed_dict(msg)
    assert result["developer_token"] == "REDACTED"
    assert result["refresh_token"] == "REDACTED"
    assert "super-secret" not in json.dumps(result)
    assert "rt" not in [result["refresh_token"]]


def test_message_to_scrubbed_dict_of_plain_dict():
    # Non-proto value (gapic hadn't coerced a dict request yet).
    result = message_to_scrubbed_dict({"client_secret": "x", "q": "value"})
    assert result["client_secret"] == "REDACTED"


def test_message_to_scrubbed_dict_redacts_bytes_fields():
    """Bytes fields (e.g. BigQuery's serialized Arrow row batches) must not be
    base64-serialized into a sample — they carry raw table data scrubadub can't see."""
    from google.cloud.bigquery_storage_v1.types import ReadRowsResponse

    msg = ReadRowsResponse()
    msg.arrow_record_batch.serialized_record_batch = b"SECRET_CUSTOMER_ROWS"
    raw = type(msg).pb(msg)

    result = message_to_scrubbed_dict(raw)
    serialized = json.dumps(result)
    assert "SECRET_CUSTOMER_ROWS" not in serialized
    # base64 of the secret must not leak either.
    assert "U0VDUkVU" not in serialized
    assert result["arrow_record_batch"]["serialized_record_batch"] == "<bytes:20>"


def test_message_to_scrubbed_dict_does_not_redact_proto_code_field():
    """`code` is a generic protobuf field name (e.g. error codes) — it must stay
    readable; only curated auth keys are redacted."""
    result = message_to_scrubbed_dict({"code": "INVALID_ARGUMENT", "developer_token": "x"})
    assert result["code"] == "INVALID_ARGUMENT"
    assert result["developer_token"] == "REDACTED"


# ---------------------------------------------------------------------------
# status matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_value,status_class,code_num,expected",
    [
        ("*", "ok", 0, True),
        ("ok", "ok", 0, True),
        ("ok", "unavailable", 14, False),
        ("unavailable", "unavailable", 14, True),
        ("resource_exhausted", "resource_exhausted", 8, True),
        ("14", "unavailable", 14, True),
        ("8", "unavailable", 14, False),
        ("server_error", "ok", 0, False),
    ],
)
def test_matches_grpc_status(rule_value, status_class, code_num, expected):
    assert _matches_grpc_status(rule_value, status_class, code_num) is expected


def test_first_match_dimensions_and_status():
    rules = (
        CaptureRule(source_type="bigquery", response_code="*", limit=5),
        CaptureRule(source_type="google_ads", response_code="unavailable", limit=5),
        CaptureRule(source_type="google_ads", response_code="*", limit=5),
    )
    match = _first_match(
        rules, source_type="google_ads", status_class="ok", status_code_num=0, team_id=99, schema_id="s"
    )
    assert match is not None
    # First two don't match (wrong source / wrong status); index 2 wins.
    assert match[0] == 2


# ---------------------------------------------------------------------------
# config cache (separate from HTTP)
# ---------------------------------------------------------------------------


def test_load_config_uses_grpc_redis_key():
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps({"capture_id": "x", "rules": []}).encode()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling.get_client",
        return_value=fake_redis,
    ):
        sampling._load_config()
    fake_redis.get.assert_called_once_with(CAPTURE_CONFIG_REDIS_KEY)


def test_is_capture_armed_reflects_config_presence():
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps({"capture_id": "x", "rules": []}).encode()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling.get_client",
        return_value=fake_redis,
    ):
        assert sampling.is_capture_armed() is True

    sampling._reset_cache_for_tests()
    fake_redis.get.return_value = None
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling.get_client",
        return_value=fake_redis,
    ):
        assert sampling.is_capture_armed() is False


@pytest.mark.parametrize(
    "limit,sequence,expected",
    [
        (0, [1], [False]),
        (2, [1, 2, 3], [True, True, False]),
    ],
)
def test_try_reserve_slot_enforces_limit(limit, sequence, expected):
    fake_redis = MagicMock()
    fake_redis.incr.side_effect = sequence
    fake_redis.ttl.return_value = 600
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling.get_client",
        return_value=fake_redis,
    ):
        results = [sampling._try_reserve_slot("cap", 0, limit) for _ in sequence]
    assert results == expected


# ---------------------------------------------------------------------------
# payload + S3 layout
# ---------------------------------------------------------------------------


def test_build_payload_scrubs_and_marks_truncation():
    request = _struct({"developer_token": "secret", "query": "SELECT 1"})
    responses = [_struct({"row": "1"}), _struct({"row": "2"})]
    record = _record(message_count=50)  # more produced than retained

    payload = json.loads(_build_sample_payload(request=request, response_messages=responses, record=record, ctx=_ctx()))

    assert payload["request"]["message"]["developer_token"] == "REDACTED"
    assert payload["request"]["method"] == "/svc/Search"
    assert payload["response"]["status_class"] == "ok"
    assert payload["response"]["truncated"] is True
    assert payload["context"]["team_id"] == 99
    assert "secret" not in json.dumps(payload)


def test_build_payload_drops_bodies_over_size_cap():
    big = _struct({"blob": "x" * (sampling.MAX_SAMPLE_BYTES)})
    record = _record(message_count=1)
    payload = json.loads(_build_sample_payload(request=_struct({}), response_messages=[big], record=record, ctx=_ctx()))
    assert payload["response"]["messages"] == []
    assert payload["response"]["dropped_for_size"] is True


def test_maybe_capture_writes_matching_sample_to_s3():
    config = CaptureConfig(
        capture_id="cap123", rules=(CaptureRule(source_type="google_ads", response_code="ok", limit=10),)
    )
    fake_redis = MagicMock()
    fake_redis.get.return_value = config.to_json().encode()
    fake_redis.incr.side_effect = [1, 1]  # reserve slot, then sequence
    fake_redis.ttl.return_value = 600

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling.get_client",
            return_value=fake_redis,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling.object_storage.write"
        ) as write,
    ):
        maybe_capture(
            request=_struct({"q": "x"}), response_messages=[_struct({"r": "1"})], record=_record(), ctx=_ctx()
        )

    assert write.called
    key = write.call_args.args[0]
    assert key.startswith(f"{S3_PREFIX}/cap123/google_ads/")
    assert key.endswith(".json")


def test_maybe_capture_noop_when_no_config():
    fake_redis = MagicMock()
    fake_redis.get.return_value = None
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling.get_client",
            return_value=fake_redis,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling.object_storage.write"
        ) as write,
    ):
        maybe_capture(request=_struct({}), response_messages=[], record=_record(), ctx=_ctx())
    write.assert_not_called()


def test_maybe_capture_noop_when_no_rule_matches():
    config = CaptureConfig(capture_id="cap", rules=(CaptureRule(source_type="bigquery", response_code="*", limit=10),))
    fake_redis = MagicMock()
    fake_redis.get.return_value = config.to_json().encode()
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling.get_client",
            return_value=fake_redis,
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling.object_storage.write"
        ) as write,
    ):
        maybe_capture(request=_struct({}), response_messages=[], record=_record(), ctx=_ctx())
    write.assert_not_called()
