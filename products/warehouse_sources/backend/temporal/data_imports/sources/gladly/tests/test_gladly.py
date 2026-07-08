import json
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.gladly import (
    CHUNK_SIZE,
    GladlyResumeConfig,
    _base_url,
    _clean_organization,
    get_rows,
    gladly_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import ENDPOINTS, GLADLY_ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gladly.gladly"


def _make_manager(resume_state: GladlyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _jobs_response(jobs: list[dict[str, Any]]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = jobs
    resp.status_code = 200
    resp.ok = True
    return resp


def _jsonl_response(rows: list[dict[str, Any]], junk_lines: list[str] | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    lines = [json.dumps(row) for row in rows] + (junk_lines or [])
    resp.iter_lines.return_value = iter(lines)
    resp.status_code = 200
    resp.ok = True
    return resp


def _job(job_id: str, updated_at: str, files: list[str] | None = None) -> dict[str, Any]:
    return {"id": job_id, "updatedAt": updated_at, "files": files or ["customers.jsonl", "agents.jsonl"]}


class TestCleanOrganization:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("myorg", "myorg"),
            ("https://myorg.gladly.com", "myorg"),
            ("myorg.gladly.com/api/v1", "myorg"),
            ("my-org", "my-org"),
        ],
    )
    def test_valid_organizations(self, value, expected):
        assert _clean_organization(value) == expected

    @pytest.mark.parametrize("value", ["", "my org", "org?x=1"])
    def test_invalid_organizations_raise(self, value):
        with pytest.raises(ValueError):
            _clean_organization(value)

    def test_base_url(self):
        assert _base_url("myorg") == "https://myorg.gladly.com/api/v1"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("myorg", "agent@x.com", "token") is expected

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_session_uses_basic_auth(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("myorg", "agent@x.com", "token")

        assert mock_session.return_value.auth == ("agent@x.com", "token")


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_processes_jobs_oldest_first_and_injects_job_fields(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j2", "2024-01-02T00:00:00.000Z"), _job("j1", "2024-01-01T00:00:00.000Z")]),
            _jsonl_response([{"id": "c1"}]),  # j1 file (oldest first)
            _jsonl_response([{"id": "c2"}]),  # j2 file
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "agent@x.com", "token", "customers", mock.MagicMock(), manager))

        flat = [row for batch in batches for row in batch]
        assert [(r["id"], r["_job_id"], r["_job_updated_at"]) for r in flat] == [
            ("c1", "j1", "2024-01-01T00:00:00.000Z"),
            ("c2", "j2", "2024-01-02T00:00:00.000Z"),
        ]
        # State saved after each fully-processed job.
        assert [call.args[0].last_job_updated_at for call in manager.save_state.call_args_list] == [
            "2024-01-01T00:00:00.000Z",
            "2024-01-02T00:00:00.000Z",
        ]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_skips_jobs_strictly_before_watermark(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j1", "2024-01-01T00:00:00.000Z"), _job("j2", "2024-01-02T00:00:00.000Z")]),
            _jsonl_response([{"id": "c2"}]),
        ]

        manager = _make_manager()
        batches = list(
            get_rows(
                "myorg",
                "agent@x.com",
                "token",
                "customers",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-01T12:00:00.000Z",
            )
        )

        flat = [row for batch in batches for row in batch]
        assert [r["id"] for r in flat] == ["c2"]
        # Only one file download happened.
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_job_sharing_watermark_timestamp_is_reprocessed(self, mock_session):
        # A late-arriving job with the same updatedAt as the watermark must not be
        # dropped — it is re-yielded and merge-on-id dedupes any overlapping rows.
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j1", "2024-01-01T00:00:00.000Z"), _job("j2", "2024-01-01T00:00:00.000Z")]),
            _jsonl_response([{"id": "c1"}]),
            _jsonl_response([{"id": "c2"}]),
        ]

        manager = _make_manager()
        batches = list(
            get_rows(
                "myorg",
                "agent@x.com",
                "token",
                "customers",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-01T00:00:00.000Z",
            )
        )

        assert [row["id"] for batch in batches for row in batch] == ["c1", "c2"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resume_state_supersedes_older_watermark(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _jobs_response(
                [
                    _job("j1", "2024-01-01T00:00:00.000Z"),
                    _job("j2", "2024-01-02T00:00:00.000Z"),
                    _job("j3", "2024-01-03T00:00:00.000Z"),
                ]
            ),
            _jsonl_response([{"id": "c3"}]),
        ]

        # Resume cutoff (between j2 and j3) supersedes the older incremental watermark,
        # so j1 and j2 are skipped and only j3 is processed.
        manager = _make_manager(GladlyResumeConfig(last_job_updated_at="2024-01-02T12:00:00.000Z"))
        batches = list(
            get_rows(
                "myorg",
                "agent@x.com",
                "token",
                "customers",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-01T00:00:00.000Z",
            )
        )

        assert [row["id"] for batch in batches for row in batch] == ["c3"]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_jobs_missing_the_stream_file_are_skipped(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j1", "2024-01-01T00:00:00.000Z", files=["topics.jsonl"])]),
        ]

        manager = _make_manager()
        assert list(get_rows("myorg", "agent@x.com", "token", "customers", mock.MagicMock(), manager)) == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_malformed_jsonl_lines_are_skipped_with_warning(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j1", "2024-01-01T00:00:00.000Z")]),
            _jsonl_response([{"id": "good"}], junk_lines=["{not json", ""]),
        ]

        manager = _make_manager()
        logger = mock.MagicMock()
        batches = list(get_rows("myorg", "agent@x.com", "token", "customers", logger, manager))

        assert [row["id"] for batch in batches for row in batch] == ["good"]
        logger.warning.assert_called_once()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_large_files_are_chunked(self, mock_session):
        rows = [{"id": str(i)} for i in range(CHUNK_SIZE + 1)]
        mock_session.return_value.get.side_effect = [
            _jobs_response([_job("j1", "2024-01-01T00:00:00.000Z")]),
            _jsonl_response(rows),
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "agent@x.com", "token", "customers", mock.MagicMock(), manager))

        assert [len(batch) for batch in batches] == [CHUNK_SIZE, 1]


class TestGladlySourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = GLADLY_ENDPOINTS[endpoint]
        response = gladly_source("myorg", "agent@x.com", "token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
