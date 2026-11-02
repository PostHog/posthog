from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.judgemereviews import (
    JudgeMeReviewsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.source import JudgeMeReviewsSource


class TestJudgeMeReviewsSource:
    def setup_method(self) -> None:
        self.source = JudgeMeReviewsSource()
        self.team_id = 123
        self.config = JudgeMeReviewsSourceConfig(shop_domain="example.myshopify.com", api_token="jm-token")

    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid_credentials", (False, "Invalid Judge.me shop domain or API token")),
            ("connect_error", (False, "Could not connect to Judge.me: boom")),
        ]
    )
    def test_validate_credentials_delegates_to_probe(self, _name: str, underlying: tuple[bool, str | None]) -> None:
        # The status → message mapping is covered by the judgeme_reviews.validate_credentials unit
        # test; here we only guard that the source passes both credentials and returns the probe
        # result unchanged.
        with mock.patch.object(source_module, "validate_credentials", return_value=underlying) as mock_validate:
            result = self.source.validate_credentials(self.config, self.team_id)
        assert result == underlying
        mock_validate.assert_called_once_with("jm-token", "example.myshopify.com")

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
