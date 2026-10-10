import json
import dataclasses

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.sequenzy import SequenzyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.source import SequenzySource


class TestSequenzySourceNonRetryableErrors:
    @pytest.mark.parametrize(
        ("status_code", "reason"),
        [
            (401, "Unauthorized"),
            (403, "Forbidden"),
        ],
    )
    def test_auth_http_errors_match_a_non_retryable_pattern(self, status_code: int, reason: str) -> None:
        # The patterns must keep matching the exact message ``requests.raise_for_status``
        # produces, or bad credentials retry until the activity times out.
        response = requests.Response()
        response.status_code = status_code
        response.url = "https://api.sequenzy.com/api/v1/subscribers"
        response.reason = reason

        with pytest.raises(requests.HTTPError) as exc_info:
            response.raise_for_status()

        patterns = SequenzySource().get_non_retryable_errors()
        assert any(pattern in str(exc_info.value) for pattern in patterns)

    def test_server_errors_stay_retryable(self) -> None:
        response = requests.Response()
        response.status_code = 503
        response.url = "https://api.sequenzy.com/api/v1/subscribers"
        response.reason = "Service Unavailable"

        with pytest.raises(requests.HTTPError) as exc_info:
            response.raise_for_status()

        patterns = SequenzySource().get_non_retryable_errors()
        assert not any(pattern in str(exc_info.value) for pattern in patterns)


class TestSequenzyResumeConfigRoundTrip:
    def test_round_trips_through_manager_serialization(self) -> None:
        # The manager serializes with dataclasses.asdict and reconstructs with
        # keyword arguments; a slotted/frozen config that breaks either would only
        # surface mid-sync in Temporal.
        original = SequenzyResumeConfig(cursor="cur_1")
        restored = SequenzyResumeConfig(**json.loads(json.dumps(dataclasses.asdict(original))))

        assert restored == original
