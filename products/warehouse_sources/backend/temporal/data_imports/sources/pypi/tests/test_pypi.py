import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.pypi.pypi import (
    MAX_PACKAGES,
    PYPI_BASE_URL,
    PyPIRetryableError,
    _fetch_project,
    _release_rows,
    _vulnerability_rows,
    get_rows,
    parse_packages,
    pypi_source,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.pypi.pypi"


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error for url: {PYPI_BASE_URL}", response=requests.Response()
        )
    return resp


def _document(name: str = "requests") -> dict[str, Any]:
    return {
        "info": {"name": name, "summary": "Python HTTP for Humans."},
        "last_serial": 42,
        "releases": {
            "2.0.0": [{"filename": f"{name}-2.0.0.tar.gz", "upload_time_iso_8601": "2013-09-24T00:00:00Z"}],
            "2.31.0": [
                {"filename": f"{name}-2.31.0-py3-none-any.whl", "upload_time_iso_8601": "2023-05-22T15:12:42Z"},
                {"filename": f"{name}-2.31.0.tar.gz", "upload_time_iso_8601": "2023-05-22T15:12:44Z"},
            ],
            "2.99.0": "not-a-list",
        },
        "vulnerabilities": [{"id": "PYSEC-2023-1", "details": "boom"}],
    }


class TestParsePackages:
    @pytest.mark.parametrize("raw", [None, "", "   \n  ", " , , "])
    def test_empty_raises(self, raw):
        with pytest.raises(ValueError):
            parse_packages(raw)

    def test_rejects_too_many_packages(self):
        raw = "\n".join(f"pkg{i}" for i in range(MAX_PACKAGES + 1))
        with pytest.raises(ValueError, match="Too many packages"):
            parse_packages(raw)


class TestReleaseRows:
    def test_skips_files_without_filename(self):
        # `filename` is part of the releases primary key, so a file object missing it can't upsert
        # cleanly and must be dropped rather than emitted with a null key component.
        document = {
            "info": {"name": "requests"},
            "releases": {
                "1.0.0": [
                    {"filename": "requests-1.0.0.tar.gz"},
                    {"upload_time_iso_8601": "2020-01-01T00:00:00Z"},
                    {"filename": ""},
                ],
            },
        }

        rows = list(_release_rows("requests", document))

        assert [r["filename"] for r in rows] == ["requests-1.0.0.tar.gz"]


class TestVulnerabilityRows:
    def test_stamps_package(self):
        rows = list(_vulnerability_rows("Requests", _document(name="requests")))

        assert len(rows) == 1
        assert rows[0]["package"] == "requests"
        assert rows[0]["id"] == "PYSEC-2023-1"


# tenacity exposes the undecorated function via `__wrapped__` so status classification can be
# asserted without waiting through retry backoff.
_fetch_once = _fetch_project.__wrapped__  # type: ignore[attr-defined]


class TestFetchProject:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(PyPIRetryableError):
            _fetch_once(session, "requests", structlog.get_logger())

    def test_other_client_error_raises(self):
        session = mock.MagicMock()
        session.get.return_value = _response(400)

        with pytest.raises(requests.HTTPError):
            _fetch_once(session, "requests", structlog.get_logger())


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (200, True),
            (404, False),
            (500, False),
        ],
    )
    def test_status_mapping(self, status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status)

            is_valid, _ = validate_credentials("requests")

        assert is_valid is expected_valid

    def test_empty_packages_is_invalid_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("")

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("requests")

        assert is_valid is False
        assert message is not None


class TestGetRows:
    def test_yields_a_batch_per_package_and_skips_404(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, _document(name="requests")),
                _response(404),
                _response(200, _document(name="django")),
            ]

            batches = list(get_rows("projects", ["requests", "nope", "django"], structlog.get_logger()))

        # The 404 package is skipped, so only two batches come back.
        assert len(batches) == 2
        assert batches[0][0]["name"] == "requests"
        assert batches[1][0]["name"] == "django"

    def test_chunks_large_release_history(self, monkeypatch):
        # A package with a large release history must not be yielded as one oversized list; it's
        # split into bounded chunks so downstream Arrow conversion stays capped.
        monkeypatch.setattr(f"{MODULE}.MAX_ROWS_PER_BATCH", 2)
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, _document(name="requests"))

            batches = list(get_rows("releases", ["requests"], structlog.get_logger()))

        # The document has 3 release files; at 2 rows per chunk that's [2, 1].
        assert [len(b) for b in batches] == [2, 1]


class TestPyPISource:
    def test_only_releases_is_partitioned(self):
        # `releases` has a stable upload timestamp; the other streams have no stable datetime column.
        releases = pypi_source("releases", "requests", structlog.get_logger())
        projects = pypi_source("projects", "requests", structlog.get_logger())

        assert releases.partition_mode == "datetime"
        assert releases.partition_keys == ["upload_time_iso_8601"]
        assert projects.partition_mode is None
        assert projects.partition_keys is None

    def test_invalid_packages_raise(self):
        with pytest.raises(ValueError):
            pypi_source("projects", "", structlog.get_logger())
