from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.source import FileUploadSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.source"


def _config(**overrides):
    source = FileUploadSource()
    return source, source.parse_config(
        {
            "table_name": "my_table",
            "file_format": "csv",
            "upload_id": "upload-abc",
            "filename": "data.csv",
            **overrides,
        }
    )


class TestFileUploadSource:
    def test_source_type(self) -> None:
        assert FileUploadSource().source_type == ExternalDataSourceType.FILEUPLOAD

    def test_schema_is_named_after_the_users_table_name(self) -> None:
        # Source create validates `payload["schemas"]` against the names `get_schemas` returns, so a
        # drift here makes every create fail with "Schemas not given".
        source, config = _config(table_name="orders_export")
        schemas = source.get_schemas(config, team_id=1)

        assert [s.name for s in schemas] == ["orders_export"]
        assert not schemas[0].supports_incremental
        assert not schemas[0].supports_append

    def test_the_uploaded_objects_location_is_server_managed(self) -> None:
        # Both fields must stay server-pinned; if either drops off, an org member could PATCH an
        # existing source to point at a different object.
        assert set(FileUploadSource().server_managed_job_input_fields({}, {})) == {"upload_id", "filename"}

    @parameterized.expand([("xlsx",), ("",), ("delta",)])
    def test_rejects_a_format_the_reader_cannot_parse(self, file_format: str) -> None:
        source, config = _config(file_format=file_format)

        valid, error = source.validate_credentials(config, team_id=1)

        assert not valid
        assert "Unsupported file format" in (error or "")

    def test_rejects_when_the_uploaded_object_is_missing(self) -> None:
        source, config = _config()
        s3 = MagicMock()
        s3.exists.return_value = False

        with patch(f"{SOURCE_MODULE}.get_s3_client", return_value=s3):
            valid, error = source.validate_credentials(config, team_id=7)

        assert not valid
        assert "Uploaded file not found" in (error or "")
        assert s3.exists.call_args.args[0].endswith("/file_uploads/team_7/upload-abc/data.csv")

    def test_accepts_an_uploaded_object_that_exists(self) -> None:
        source, config = _config()
        s3 = MagicMock()
        s3.exists.return_value = True

        with patch(f"{SOURCE_MODULE}.get_s3_client", return_value=s3):
            assert source.validate_credentials(config, team_id=7) == (True, None)
