import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table import (
    RepartitionActivityInputs,
    _maybe_flag_pre_extraction,
    _maybe_repartition_table,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table"

TEAM_ID = 1
SCHEMA_ID = str(uuid.uuid4())
JOB_ID = str(uuid.uuid4())
SOURCE_ID = str(uuid.uuid4())

PENDING_TARGET = {
    "partition_mode": "datetime",
    "partition_format": "day",
    "partition_count": None,
    "partition_size": None,
    "partition_keys": ["created_at"],
    "trigger_reason": "proactive_threshold",
    "attempts": 0,
}


def _schema(*, name: str, s3_folder_name: str | None) -> MagicMock:
    schema = MagicMock()
    schema.id = SCHEMA_ID
    schema.name = name
    schema.s3_folder_name = s3_folder_name
    schema.resolved_s3_folder_name = s3_folder_name
    schema.team_id = TEAM_ID
    schema.delta_revive_required = None
    schema.repartition_swap = None
    schema.repartition_pending = PENDING_TARGET
    return schema


class TestRepartitionActivityDeltaFolder:
    @pytest.mark.parametrize(
        "name, s3_folder_name, expected_resource_name",
        [
            ("public.posthog_externaldatajob", "posthog_externaldatajob", "posthog_externaldatajob"),
            ("stripe_charge", None, "stripe_charge"),
        ],
        ids=["folder_pinned_by_multi_schema_rename", "folder_derived_from_name"],
    )
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableHelper")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_repartitions_the_folder_the_pipeline_wrote_to(
        self,
        mock_schema_model: MagicMock,
        mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        _mock_capture: MagicMock,
        name: str,
        s3_folder_name: str | None,
        expected_resource_name: str,
    ) -> None:
        schema = _schema(name=name, s3_folder_name=s3_folder_name)
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.return_value = {"outcome": "completed"}

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        assert mock_helper_cls.call_args.kwargs["resource_name"] == expected_resource_name
        assert mock_repartition.await_count == 1
        await_args = mock_repartition.await_args
        assert await_args is not None
        assert await_args.kwargs["helper"] is mock_helper_cls.return_value
        assert mock_job_model.objects.get.call_args.kwargs == {"id": JOB_ID}


class TestMaybeFlagPreExtraction:
    @parameterized.expand(
        [
            (
                "generic_s3_error",
                OSError(
                    "Generic S3 error: Error getting list response body: HTTP error: "
                    "request or response body error: operation timed out"
                ),
            ),
            (
                "credential_provider_timeout",
                OSError(
                    "Operation not supported: an error occurred while loading credentials: "
                    "dispatch failure: timeout: client error (Connect): HTTP connect timeout occurred: timed out"
                ),
            ),
        ]
    )
    @patch(f"{MODULE}.capture_exception")
    def test_transient_object_store_error_is_not_reported(
        self, _name: str, error: OSError, mock_capture: MagicMock
    ) -> None:
        schema = _schema(name="stripe_charge", s3_folder_name=None)
        helper = MagicMock()
        helper.get_delta_table = AsyncMock(side_effect=error)

        result = _maybe_flag_pre_extraction(schema, MagicMock(), helper, MagicMock(), enabled=True)

        assert result is None
        mock_capture.assert_not_called()

    @patch(f"{MODULE}.capture_exception")
    def test_non_transient_error_is_still_reported(self, mock_capture: MagicMock) -> None:
        schema = _schema(name="stripe_charge", s3_folder_name=None)
        helper = MagicMock()
        error = ValueError("unexpected schema drift")
        helper.get_delta_table = AsyncMock(side_effect=error)

        result = _maybe_flag_pre_extraction(schema, MagicMock(), helper, MagicMock(), enabled=True)

        assert result is None
        mock_capture.assert_called_once_with(error)
