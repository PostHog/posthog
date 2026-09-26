import json
import dataclasses

import pytest
from unittest.mock import MagicMock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.sequenzy import (
    SequenzyResumeConfig,
    sequenzy_source,
)
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


class TestSequenzySourceResponse:
    def _source_response(self, endpoint: str):
        manager = MagicMock()
        manager.can_resume.return_value = False
        return sequenzy_source(
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
        )

    @pytest.mark.parametrize("endpoint", ["subscribers", "campaigns", "sequences"])
    def test_growing_collections_partition_on_created_at(self, endpoint: str) -> None:
        response = self._source_response(endpoint)

        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    @pytest.mark.parametrize("endpoint", ["tags", "lists", "segments", "email_metrics"])
    def test_unpartitionable_collections_get_no_partitioning(self, endpoint: str) -> None:
        response = self._source_response(endpoint)

        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_email_metrics_key_spans_both_id_namespaces(self) -> None:
        # `emailId` alone is a campaign ID for campaigns and an automation node ID for
        # sequence steps; a single-column key would multi-match on a collision and
        # merges would degrade every sync.
        response = self._source_response("email_metrics")

        assert response.primary_keys == ["emailType", "emailId"]


class TestSequenzyResumeConfigRoundTrip:
    def test_round_trips_through_manager_serialization(self) -> None:
        # The manager serializes with dataclasses.asdict and reconstructs with
        # keyword arguments; a slotted/frozen config that breaks either would only
        # surface mid-sync in Temporal.
        original = SequenzyResumeConfig(cursor="cur_1")
        restored = SequenzyResumeConfig(**json.loads(json.dumps(dataclasses.asdict(original))))

        assert restored == original
