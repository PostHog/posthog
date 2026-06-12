import os
import tempfile

import pytest
from posthog.test.base import APIBaseTest

from django.test import override_settings

from products.exports.backend.models.exported_asset import (
    ExportContentTooLargeForDatabase,
    ExportedAsset,
    save_content,
    save_content_from_file,
    save_content_to_exported_asset,
)
from products.exports.backend.tasks.failure_handler import EXCEPTIONS_TO_RETRY, FAILURE_TYPE_USER, classify_failure_type


class TestExportedAssetDbFallback(APIBaseTest):
    def _create_asset(self) -> ExportedAsset:
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.CSV,
        )
        return asset

    @override_settings(OBJECT_STORAGE_ENABLED=False, EXPORTED_ASSET_MAX_DB_FALLBACK_BYTES=10)
    def test_save_content_to_exported_asset_writes_small_content(self) -> None:
        asset = self._create_asset()
        save_content_to_exported_asset(asset, b"small")
        asset.refresh_from_db()
        assert asset.content == b"small"

    @override_settings(OBJECT_STORAGE_ENABLED=False, EXPORTED_ASSET_MAX_DB_FALLBACK_BYTES=10)
    def test_save_content_to_exported_asset_rejects_oversized_content(self) -> None:
        asset = self._create_asset()
        with pytest.raises(ExportContentTooLargeForDatabase):
            save_content_to_exported_asset(asset, b"x" * 11)
        asset.refresh_from_db()
        assert asset.content is None

    @override_settings(OBJECT_STORAGE_ENABLED=False, EXPORTED_ASSET_MAX_DB_FALLBACK_BYTES=10)
    def test_save_content_rejects_oversized_content_on_db_fallback(self) -> None:
        asset = self._create_asset()
        with pytest.raises(ExportContentTooLargeForDatabase):
            save_content(asset, b"x" * 11)

    @override_settings(OBJECT_STORAGE_ENABLED=False, EXPORTED_ASSET_MAX_DB_FALLBACK_BYTES=10)
    def test_save_content_from_file_writes_small_file_to_db(self) -> None:
        asset = self._create_asset()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"small")
            path = f.name
        try:
            save_content_from_file(asset, path)
        finally:
            os.unlink(path)
        asset.refresh_from_db()
        assert asset.content == b"small"

    @override_settings(OBJECT_STORAGE_ENABLED=False, EXPORTED_ASSET_MAX_DB_FALLBACK_BYTES=10)
    def test_save_content_from_file_rejects_oversized_file_on_db_fallback(self) -> None:
        asset = self._create_asset()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"x" * 11)
            path = f.name
        try:
            with pytest.raises(ExportContentTooLargeForDatabase):
                save_content_from_file(asset, path)
        finally:
            os.unlink(path)
        asset.refresh_from_db()
        assert asset.content is None

    def test_oversize_error_is_classified_as_user_and_non_retryable(self) -> None:
        assert classify_failure_type(ExportContentTooLargeForDatabase()) == FAILURE_TYPE_USER
        assert ExportContentTooLargeForDatabase not in EXCEPTIONS_TO_RETRY
