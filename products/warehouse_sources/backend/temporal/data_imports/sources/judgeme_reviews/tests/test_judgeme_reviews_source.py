import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.judgemereviews import (
    JudgeMeReviewsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.source import JudgeMeReviewsSource


class TestJudgeMeReviewsSource:
    def setup_method(self) -> None:
        self.source = JudgeMeReviewsSource()
        self.team_id = 123
        self.config = JudgeMeReviewsSourceConfig(shop_domain="example.myshopify.com", api_token="jm-token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.source.judgeme_reviews_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "reviews"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "jm-token"
        assert kwargs["shop_domain"] == "example.myshopify.com"
        assert kwargs["endpoint"] == "reviews"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Judge.me schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
