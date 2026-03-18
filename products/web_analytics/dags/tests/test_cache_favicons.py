import pytest
from unittest.mock import Mock, patch

from products.web_analytics.dags.cache_favicons import (
    get_authorized_domains,
    get_last_cached_domains,
    upload_if_missing,
)


class TestGetLastCachedDomains:
    @pytest.mark.parametrize(
        "asset_key",
        ["cache_favicons", "cache_authorized_domain_favicons"],
        ids=["referrer_asset", "authorized_asset"],
    )
    def test_returns_empty_set_when_no_materialization(self, asset_key):
        context = Mock()
        context.instance.get_latest_materialization_event.return_value = None

        result = get_last_cached_domains(context, asset_key)

        assert result == set()

    def test_returns_empty_set_when_no_asset_materialization(self):
        context = Mock()
        event = Mock()
        event.asset_materialization = None
        context.instance.get_latest_materialization_event.return_value = event

        result = get_last_cached_domains(context, "cache_favicons")

        assert result == set()

    def test_returns_empty_set_when_no_cached_domains_metadata(self):
        context = Mock()
        event = Mock()
        event.asset_materialization.metadata = {}
        context.instance.get_latest_materialization_event.return_value = event

        result = get_last_cached_domains(context, "cache_favicons")

        assert result == set()

    def test_returns_cached_domains_from_metadata(self):
        import dagster

        context = Mock()
        event = Mock()
        event.asset_materialization.metadata = {
            "cached_domains": dagster.JsonMetadataValue(["example.com", "test.org"])
        }
        context.instance.get_latest_materialization_event.return_value = event

        result = get_last_cached_domains(context, "cache_favicons")

        assert result == {"example.com", "test.org"}


class TestGetAuthorizedDomains:
    @pytest.mark.parametrize(
        "app_urls_rows,expected",
        [
            ([], set()),
            ([["https://example.com"]], {"example.com"}),
            ([["https://example.com", "https://other.org"]], {"example.com", "other.org"}),
            ([["https://example.com"], ["https://other.org"]], {"example.com", "other.org"}),
            # Deduplicates across teams
            ([["https://example.com"], ["https://example.com"]], {"example.com"}),
            # Strips ports
            ([["https://example.com:8080"]], {"example.com"}),
            # Handles bare domains without scheme
            ([["example.com"]], {"example.com"}),
            # Skips wildcard patterns
            ([["https://*.example.com"]], set()),
            ([["https://*.example.com", "https://real.com"]], {"real.com"}),
            # Skips empty/null entries
            ([["", None, "https://valid.com"]], {"valid.com"}),
        ],
        ids=[
            "no_teams",
            "single_url",
            "multiple_urls_one_team",
            "one_url_per_team",
            "deduplicates",
            "strips_port",
            "bare_domain",
            "skips_wildcard",
            "wildcard_with_real",
            "skips_empty_and_none",
        ],
    )
    def test_extracts_domains(self, app_urls_rows, expected):
        context = Mock()
        with patch("products.web_analytics.dags.cache_favicons.Team") as mock_team:
            mock_team.objects.exclude.return_value.values_list.return_value.iterator.return_value = iter(app_urls_rows)
            result = get_authorized_domains(context)

        assert result == expected


class TestUploadIfMissing:
    def test_skips_upload_when_object_exists(self):
        context = Mock()
        s3_client = Mock()
        s3_client.head_object.return_value = {}

        result = upload_if_missing(context, s3_client, "bucket", "key", b"data", "image/png")

        assert result == "key"
        s3_client.put_object.assert_not_called()

    def test_uploads_when_object_missing(self):
        context = Mock()
        s3_client = Mock()

        class ClientError(Exception):
            pass

        s3_client.exceptions.ClientError = ClientError
        s3_client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

        result = upload_if_missing(context, s3_client, "bucket", "key", b"data", "image/png")

        assert result == "key"
        s3_client.put_object.assert_called_once_with(
            Bucket="bucket",
            Key="key",
            Body=b"data",
            ContentType="image/png",
        )


class TestCacheFaviconsAsset:
    @patch("products.web_analytics.dags.cache_favicons.httpx.Client")
    @patch("products.web_analytics.dags.cache_favicons.sync_execute")
    @patch("products.web_analytics.dags.cache_favicons.get_last_cached_domains")
    @patch("products.web_analytics.dags.cache_favicons.download_favicon")
    @patch("products.web_analytics.dags.cache_favicons.upload_if_missing")
    def test_skips_previously_cached_domains(
        self, mock_upload, mock_download, mock_get_cached, mock_sync_execute, mock_httpx_client
    ):
        import dagster

        from products.web_analytics.dags.cache_favicons import CacheFaviconsConfig, cache_favicons

        mock_sync_execute.return_value = [("cached.com", 5000), ("new.com", 2000)]
        mock_get_cached.return_value = {"cached.com"}
        mock_download.return_value = ("new.com", b"data", "image/png", "http://url")

        context = dagster.build_asset_context()
        s3 = Mock()
        s3.get_client.return_value = Mock()
        config = CacheFaviconsConfig(force_refresh=False)

        with patch("products.web_analytics.dags.cache_favicons.settings") as mock_settings:
            mock_settings.DAGSTER_FAVICONS_S3_BUCKET = "test-bucket"
            result: dagster.MaterializeResult = cache_favicons(context, s3, config)  # type: ignore[assignment]

        mock_download.assert_called_once()
        assert result.metadata is not None
        assert result.metadata["domains_skipped"] == 1
        assert result.metadata["favicons_cached"] == 1

    @patch("products.web_analytics.dags.cache_favicons.httpx.Client")
    @patch("products.web_analytics.dags.cache_favicons.sync_execute")
    @patch("products.web_analytics.dags.cache_favicons.get_last_cached_domains")
    @patch("products.web_analytics.dags.cache_favicons.download_favicon")
    @patch("products.web_analytics.dags.cache_favicons.upload_if_missing")
    def test_force_refresh_downloads_all(
        self, mock_upload, mock_download, mock_get_cached, mock_sync_execute, mock_httpx_client
    ):
        import dagster

        from products.web_analytics.dags.cache_favicons import CacheFaviconsConfig, cache_favicons

        mock_sync_execute.return_value = [("cached.com", 5000), ("new.com", 2000)]
        mock_download.side_effect = [
            ("cached.com", b"data1", "image/png", "http://url1"),
            ("new.com", b"data2", "image/png", "http://url2"),
        ]

        context = dagster.build_asset_context()
        s3 = Mock()
        s3.get_client.return_value = Mock()
        config = CacheFaviconsConfig(force_refresh=True)

        with patch("products.web_analytics.dags.cache_favicons.settings") as mock_settings:
            mock_settings.DAGSTER_FAVICONS_S3_BUCKET = "test-bucket"
            result: dagster.MaterializeResult = cache_favicons(context, s3, config)  # type: ignore[assignment]

        mock_get_cached.assert_not_called()
        assert mock_download.call_count == 2
        assert result.metadata is not None
        assert result.metadata["domains_skipped"] == 0
        assert result.metadata["favicons_cached"] == 2


class TestCacheAuthorizedDomainFaviconsAsset:
    @patch("products.web_analytics.dags.cache_favicons.httpx.Client")
    @patch("products.web_analytics.dags.cache_favicons.get_authorized_domains")
    @patch("products.web_analytics.dags.cache_favicons.get_last_cached_domains")
    @patch("products.web_analytics.dags.cache_favicons.download_favicon")
    @patch("products.web_analytics.dags.cache_favicons.upload_if_missing")
    def test_fetches_favicons_for_authorized_domains(
        self, mock_upload, mock_download, mock_get_cached, mock_get_authorized, mock_httpx_client
    ):
        import dagster

        from products.web_analytics.dags.cache_favicons import CacheFaviconsConfig, cache_authorized_domain_favicons

        mock_get_authorized.return_value = {"mysite.com", "other.com"}
        mock_get_cached.return_value = set()
        mock_download.side_effect = [
            ("mysite.com", b"data1", "image/png", "http://url1"),
            ("other.com", b"data2", "image/png", "http://url2"),
        ]

        context = dagster.build_asset_context()
        s3 = Mock()
        s3.get_client.return_value = Mock()
        config = CacheFaviconsConfig(force_refresh=False)

        with patch("products.web_analytics.dags.cache_favicons.settings") as mock_settings:
            mock_settings.DAGSTER_FAVICONS_S3_BUCKET = "test-bucket"
            result: dagster.MaterializeResult = cache_authorized_domain_favicons(context, s3, config)  # type: ignore[assignment]

        assert mock_download.call_count == 2
        assert result.metadata is not None
        assert result.metadata["authorized_domains_queried"] == 2
        assert result.metadata["favicons_cached"] == 2

    @patch("products.web_analytics.dags.cache_favicons.httpx.Client")
    @patch("products.web_analytics.dags.cache_favicons.get_authorized_domains")
    @patch("products.web_analytics.dags.cache_favicons.get_last_cached_domains")
    @patch("products.web_analytics.dags.cache_favicons.download_favicon")
    @patch("products.web_analytics.dags.cache_favicons.upload_if_missing")
    def test_skips_previously_cached_authorized_domains(
        self, mock_upload, mock_download, mock_get_cached, mock_get_authorized, mock_httpx_client
    ):
        import dagster

        from products.web_analytics.dags.cache_favicons import CacheFaviconsConfig, cache_authorized_domain_favicons

        mock_get_authorized.return_value = {"cached.com", "new.com"}
        mock_get_cached.return_value = {"cached.com"}
        mock_download.return_value = ("new.com", b"data", "image/png", "http://url")

        context = dagster.build_asset_context()
        s3 = Mock()
        s3.get_client.return_value = Mock()
        config = CacheFaviconsConfig(force_refresh=False)

        with patch("products.web_analytics.dags.cache_favicons.settings") as mock_settings:
            mock_settings.DAGSTER_FAVICONS_S3_BUCKET = "test-bucket"
            result: dagster.MaterializeResult = cache_authorized_domain_favicons(context, s3, config)  # type: ignore[assignment]

        mock_download.assert_called_once()
        assert result.metadata is not None
        assert result.metadata["domains_skipped"] == 1
        assert result.metadata["favicons_cached"] == 1
