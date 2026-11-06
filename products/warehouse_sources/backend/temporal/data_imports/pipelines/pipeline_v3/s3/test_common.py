from datetime import UTC, datetime, timedelta, timezone

import pytest
from unittest.mock import patch

from django.test import override_settings

from botocore.exceptions import ClientError
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common import (
    ensure_bucket,
    get_base_folder,
    get_date_partition,
)
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException


class TestGetDatePartition:
    @parameterized.expand(
        [
            ("midday_utc", datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC), "dt=2026-05-22"),
            ("just_before_midnight_utc", datetime(2026, 5, 22, 23, 59, 59, tzinfo=UTC), "dt=2026-05-22"),
            ("just_after_midnight_utc", datetime(2026, 5, 23, 0, 0, 1, tzinfo=UTC), "dt=2026-05-23"),
        ]
    )
    def test_formats_utc_datetime(self, _name: str, dt: datetime, expected: str) -> None:
        assert get_date_partition(dt) == expected

    def test_converts_non_utc_to_utc_date(self) -> None:
        la = timezone(timedelta(hours=-7))
        dt = datetime(2026, 5, 22, 19, 0, 0, tzinfo=la)

        assert get_date_partition(dt) == "dt=2026-05-23"

    def test_is_pure_function_of_input(self) -> None:
        created_at = datetime(2026, 5, 22, 23, 59, 0, tzinfo=UTC)

        assert get_date_partition(created_at) == get_date_partition(created_at) == "dt=2026-05-22"


class TestGetBaseFolder:
    def test_places_partition_before_team_id(self) -> None:
        folder = get_base_folder(team_id=42, schema_id="schema-a", run_uuid="run-b", date_partition="dt=2026-05-22")

        assert folder.endswith("/data_pipelines_extract/dt=2026-05-22/42/schema-a/run-b")


class TestEnsureBucket:
    @parameterized.expand(
        [
            ("status_only_code", {"Error": {"Code": "403"}}),
            ("named_code", {"Error": {"Code": "AccessDenied"}}),
            (
                "status_in_metadata",
                {"Error": {"Code": "SignatureDoesNotMatch"}, "ResponseMetadata": {"HTTPStatusCode": 403}},
            ),
        ]
    )
    @override_settings(USE_LOCAL_SETUP=True)
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common.ensure_bucket_exists"
    )
    def test_refused_bucket_check_is_not_retried(self, _name: str, response: dict, mock_ensure) -> None:
        # ensure_bucket_exists has already retried this refusal, so the raw ClientError only made
        # the activity retry a configuration failure and report a fresh exception on every attempt.
        mock_ensure.side_effect = ClientError(response, "HeadBucket")  # type: ignore[arg-type]

        with pytest.raises(NonRetryableException):
            ensure_bucket()

    @override_settings(USE_LOCAL_SETUP=True)
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common.ensure_bucket_exists"
    )
    def test_other_client_errors_stay_retryable(self, mock_ensure) -> None:
        mock_ensure.side_effect = ClientError({"Error": {"Code": "500"}}, "HeadBucket")

        with pytest.raises(ClientError):
            ensure_bucket()
