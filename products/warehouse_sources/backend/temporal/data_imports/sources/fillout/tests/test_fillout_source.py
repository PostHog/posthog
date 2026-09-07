from typing import Any, cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.source import FilloutSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fillout import (
    FilloutSourceConfig,
)


class TestFilloutSource:
    def setup_method(self) -> None:
        self.source = FilloutSource()
        self.team_id = 123
        self.config = FilloutSourceConfig(api_key="fillout-key")

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # `forms` only exposes formId/name — no server-side timestamp filter, so full refresh.
        assert schemas["forms"].supports_incremental is False
        assert schemas["forms"].incremental_fields == []

        # `submissions` supports incremental via the server-side `afterDate` filter on submissionTime.
        assert schemas["submissions"].supports_incremental is True
        assert schemas["submissions"].supports_append is True
        assert [f["field"] for f in schemas["submissions"].incremental_fields] == ["submissionTime"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["submissions"])
        assert len(schemas) == 1
        assert schemas[0].name == "submissions"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.fillout.com/v1/api/forms",
            "403 Client Error: Forbidden for url: https://api.fillout.com/v1/api/forms",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        ["500 Server Error for url: https://api.fillout.com/v1/api/forms"],
    )
    def test_non_retryable_errors_ignore_unrelated(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_validate_credentials_rejects_unknown_api_base_url(self) -> None:
        config = FilloutSourceConfig(api_key="fillout-key", api_base_url=cast(Any, "https://api.fillout.com"))
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and "API base URL must be one of" in message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.fillout.source.validate_fillout_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name="submissions")

        assert result == (True, None)
        kwargs = mock_validate.call_args.kwargs
        assert kwargs["api_key"] == "fillout-key"
        assert kwargs["api_base_url"] == "https://api.fillout.com/v1/api"
        assert kwargs["schema_name"] == "submissions"
