import io
import json
import zipfile
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualtrics import (
    QualtricsAuthMethodConfig,
    QualtricsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics import qualtrics as qualtrics_module
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics.qualtrics import (
    EXPORT_FAILED_ERROR,
    QualtricsAuthManager,
    QualtricsClient,
    QualtricsConfigurationError,
    QualtricsCredentials,
    QualtricsExportFailedError,
    QualtricsHostNotAllowedError,
    QualtricsPaginationLimitError,
    QualtricsResponseTooLargeError,
    QualtricsResumeConfig,
    QualtricsRetryableError,
    _guard_response,
    _iter_export_file,
    _read_capped,
    format_incremental_value,
    validate_credentials,
    validate_host,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics.source import QualtricsSource

HOST = "iad1.qualtrics.com"
BASE = f"https://{HOST}/API/v3"
API_TOKEN_CREDENTIALS = QualtricsCredentials(method="api_token", api_token="tok-123")
OAUTH_CREDENTIALS = QualtricsCredentials(method="oauth_client_credentials", client_id="client", client_secret="shhh")


def _response(*, status_code: int = 200, json_data: Any = None, body: bytes | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    payload = body if body is not None else (json.dumps(json_data).encode() if json_data is not None else b"")
    # Bodies are read with stream=True + iter_content, so serve them in that shape. A fresh
    # iterator per call lets one mock response stand in for repeated reads.
    response.iter_content.side_effect = lambda *args, **kwargs: iter([payload] if payload else [])
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: for url: {BASE}", response=response
        )
    return response


def _collection(elements: list[dict[str, Any]], next_page: str | None = None) -> dict[str, Any]:
    return {"result": {"elements": elements, "nextPage": next_page}, "meta": {"httpStatus": "200 - OK"}}


def _session(get_responses: list[Any] | None = None, post_responses: list[Any] | None = None) -> mock.MagicMock:
    session = mock.MagicMock()
    if get_responses is not None:
        session.get.side_effect = get_responses
    if post_responses is not None:
        session.post.side_effect = post_responses
    return session


def _zip_bytes(name: str, content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def _multi_member_zip_bytes(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _zip_with_spoofed_low_member_count(members: dict[str, str]) -> bytes:
    """Append a second EOCD that lies about the member count while keeping the real directory size.

    zipfile selects the trailing EOCD and reads the central directory by its byte length, so a
    guard that trusts the entry-count field would wave this through.
    """
    raw = _multi_member_zip_bytes(members)
    marker = raw.rfind(b"PK\x05\x06")
    spoofed = bytearray(raw[marker:])
    spoofed[8:10] = (1).to_bytes(2, "little")  # entries on this disk
    spoofed[10:12] = (1).to_bytes(2, "little")  # total entries
    return raw + bytes(spoofed)


def _config() -> QualtricsSourceConfig:
    return QualtricsSourceConfig(
        datacenter_id="iad1",
        auth_method=QualtricsAuthMethodConfig(selection="api_token", api_token="tok-123"),
    )


def _drive(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    return SourceDriver(QualtricsSource(), _config()).run(endpoint, script, **inputs)


def _json(payload: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=payload)


class TestQualtricsTransport:
    @pytest.mark.parametrize("raw", ["", "   ", "bad host", "iad1.qualtrics.com:8080", "iad1_@"])
    def test_validate_host_rejects_junk(self, raw: str) -> None:
        with pytest.raises(QualtricsConfigurationError):
            validate_host(raw)

    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
        ],
    )
    def test_format_incremental_value(self, value: Any, expected: str) -> None:
        assert format_incremental_value(value) == expected

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_guard_response_classifies_retryable(self, status_code: int) -> None:
        with pytest.raises(QualtricsRetryableError):
            _guard_response(_response(status_code=status_code), BASE)

    @pytest.mark.parametrize("status_code", [301, 302, 307, 308])
    def test_guard_response_refuses_redirects(self, status_code: int) -> None:
        with pytest.raises(QualtricsHostNotAllowedError):
            _guard_response(_response(status_code=status_code), BASE)

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_guard_response_raises_for_client_errors(self, status_code: int) -> None:
        with pytest.raises(requests.HTTPError):
            _guard_response(_response(status_code=status_code), BASE)

    def test_read_capped_refuses_oversized_body(self) -> None:
        with pytest.raises(QualtricsResponseTooLargeError):
            _read_capped(_response(body=b"x" * 1024), max_bytes=10)

    def test_api_token_missing_is_a_configuration_error(self) -> None:
        manager = QualtricsAuthManager(_session(), HOST, QualtricsCredentials(method="api_token"))
        with pytest.raises(QualtricsConfigurationError):
            manager.headers()

    def test_oauth_token_is_minted_once_and_cached(self) -> None:
        session = _session(post_responses=[_response(json_data={"access_token": "abc", "expires_in": 3600})])
        manager = QualtricsAuthManager(session, HOST, OAUTH_CREDENTIALS)

        assert manager.headers()["Authorization"] == "Bearer abc"
        assert manager.headers()["Authorization"] == "Bearer abc"
        assert session.post.call_count == 1
        assert session.post.call_args.args[0] == f"https://{HOST}/oauth2/token"

    def test_oauth_without_client_credentials_is_a_configuration_error(self) -> None:
        manager = QualtricsAuthManager(_session(), HOST, QualtricsCredentials(method="oauth_client_credentials"))
        with pytest.raises(QualtricsConfigurationError):
            manager.headers()

    @pytest.mark.parametrize(
        "url",
        [
            "http://iad1.qualtrics.com/API/v3/surveys",
            "https://evil.example.com/API/v3/surveys",
            "https://169.254.169.254/latest/meta-data",
        ],
    )
    def test_client_refuses_urls_off_the_configured_host(self, url: str) -> None:
        with scripted_network([]) as network:
            client = QualtricsClient(HOST, API_TOKEN_CREDENTIALS, "v3")
            with pytest.raises(QualtricsHostNotAllowedError):
                client.get_json(url)

        assert network.requests_log == []


class TestCollectionPagination:
    def test_empty_collection_yields_nothing(self) -> None:
        result = _drive("groups", [_json(_collection([]))])

        assert result.raised is None
        assert result.items == []

    def test_pagination_that_never_terminates_is_capped(self) -> None:
        script = always(_json(_collection([{"id": "UR_1"}], next_page=f"{BASE}/users?p=1")))

        with mock.patch.object(qualtrics_module, "MAX_PAGES", 3):
            result = _drive("users", script)

        assert isinstance(result.raised, QualtricsPaginationLimitError)

    @pytest.mark.parametrize(
        "endpoint, script, expected",
        [
            ("directories", [_json(_collection([{"directoryId": "POOL_1"}]))], ["true"]),
            (
                "mailing_lists",
                [_json(_collection([{"directoryId": "POOL_1"}])), _json(_collection([{"mailingListId": "CG_1"}]))],
                [None, "true"],
            ),
            ("users", [_json(_collection([{"id": "UR_1"}]))], [None]),
        ],
    )
    def test_contact_counts_are_requested_only_where_declared(
        self, endpoint: str, script: list[ScriptedResponse], expected: list[str | None]
    ) -> None:
        result = _drive(endpoint, script)

        assert result.raised is None
        assert result.params("includeCount") == expected


class TestSurveyFanout:
    @pytest.mark.parametrize(
        "endpoint, script, expected_items, expected_paths, expected_child_states",
        [
            (
                "distributions",
                [
                    _json(_collection([{"id": "SV_1"}, {"id": "SV_2"}])),
                    _json(_collection([{"id": "EMD_1"}])),
                    _json(_collection([{"id": "EMD_2"}])),
                ],
                [[{"id": "EMD_1", "surveyId": "SV_1"}], [{"id": "EMD_2", "surveyId": "SV_2"}]],
                ["/API/v3/surveys", "/API/v3/distributions", "/API/v3/distributions"],
                [[], []],
            ),
            (
                "directory_contacts",
                [
                    _json(_collection([{"directoryId": "POOL_1"}, {"directoryId": "POOL_2"}])),
                    _json(
                        _collection(
                            [{"contactId": "CID_1"}], next_page=f"{BASE}/directories/POOL_1/contacts?skipToken=a"
                        )
                    ),
                    _json(_collection([{"contactId": "CID_2"}])),
                    _json(_collection([{"contactId": "CID_3"}])),
                ],
                [
                    [{"contactId": "CID_1", "directoryId": "POOL_1"}],
                    [{"contactId": "CID_2", "directoryId": "POOL_1"}],
                    [{"contactId": "CID_3", "directoryId": "POOL_2"}],
                ],
                [
                    "/API/v3/directories",
                    "/API/v3/directories/POOL_1/contacts",
                    "/API/v3/directories/POOL_1/contacts",
                    "/API/v3/directories/POOL_2/contacts",
                ],
                [
                    [
                        QualtricsResumeConfig(
                            parent_id="POOL_1", child_next_page=f"{BASE}/directories/POOL_1/contacts?skipToken=a"
                        ),
                        QualtricsResumeConfig(parent_id="POOL_1"),
                    ],
                    [QualtricsResumeConfig(parent_index=1, parent_id="POOL_2")],
                ],
            ),
            (
                "mailing_lists",
                [
                    _json(_collection([{"directoryId": "POOL_1"}, {"directoryId": "POOL_2"}])),
                    _json(_collection([{"mailingListId": "CG_1"}])),
                    _json(_collection([{"mailingListId": "CG_2"}])),
                ],
                [
                    [{"mailingListId": "CG_1", "directoryId": "POOL_1"}],
                    [{"mailingListId": "CG_2", "directoryId": "POOL_2"}],
                ],
                [
                    "/API/v3/directories",
                    "/API/v3/directories/POOL_1/mailinglists",
                    "/API/v3/directories/POOL_2/mailinglists",
                ],
                [
                    [QualtricsResumeConfig(parent_id="POOL_1")],
                    [QualtricsResumeConfig(parent_index=1, parent_id="POOL_2")],
                ],
            ),
            (
                "distribution_history",
                [
                    _json(_collection([{"id": "SV_1"}, {"id": "SV_2"}])),
                    _json(_collection([{"id": "EMD_1"}, {"id": "EMD/../x"}, {"id": "EMD_2"}])),
                    _json(
                        _collection(
                            [{"contactId": "CID_1"}], next_page=f"{BASE}/distributions/EMD_1/history?skipToken=a"
                        )
                    ),
                    _json(_collection([{"contactId": "CID_2"}])),
                    _json(_collection([])),
                    _json(_collection([])),
                ],
                [
                    [{"contactId": "CID_1", "surveyId": "SV_1", "distributionId": "EMD_1"}],
                    [{"contactId": "CID_2", "surveyId": "SV_1", "distributionId": "EMD_1"}],
                ],
                [
                    "/API/v3/surveys",
                    "/API/v3/distributions",
                    "/API/v3/distributions/EMD_1/history",
                    "/API/v3/distributions/EMD_1/history",
                    "/API/v3/distributions/EMD_2/history",
                    "/API/v3/distributions",
                ],
                [
                    [
                        QualtricsResumeConfig(
                            parent_id="SV_1",
                            child_id="EMD_1",
                            child_next_page=f"{BASE}/distributions/EMD_1/history?skipToken=a",
                        ),
                        QualtricsResumeConfig(parent_id="SV_1", child_id="EMD_1"),
                        QualtricsResumeConfig(parent_id="SV_1", child_id="EMD_2"),
                    ],
                    [],
                ],
            ),
        ],
    )
    def test_fanout_stamps_the_parent_id(
        self,
        endpoint: str,
        script: list[ScriptedResponse],
        expected_items: list[list[dict[str, Any]]],
        expected_paths: list[str],
        expected_child_states: list[list[QualtricsResumeConfig]],
    ) -> None:
        result = _drive(endpoint, script)

        assert result.raised is None
        assert result.items == expected_items
        assert result.paths == expected_paths
        assert result.saved_states == [
            *expected_child_states[0],
            QualtricsResumeConfig(parent_index=1),
            *expected_child_states[1],
            QualtricsResumeConfig(parent_index=2),
        ]

    def test_over_length_survey_ids_are_dropped(self) -> None:
        with mock.patch.object(qualtrics_module, "MAX_PARENT_ID_LENGTH", 5):
            result = _drive(
                "survey_questions",
                [
                    _json(_collection([{"id": "SV_toolong"}, {"id": "SV_ok"}])),
                    _json(_collection([{"QuestionID": "QID1"}])),
                ],
            )

        assert result.items == [[{"QuestionID": "QID1", "surveyId": "SV_ok"}]]

    def test_too_many_surveys_is_refused(self) -> None:
        with mock.patch.object(qualtrics_module, "MAX_PARENT_COUNT", 1):
            result = _drive("survey_questions", [_json(_collection([{"id": "SV_1"}, {"id": "SV_2"}]))])

        assert isinstance(result.raised, QualtricsResponseTooLargeError)

    def test_resumes_after_the_last_completed_survey(self) -> None:
        result = _drive(
            "survey_questions",
            [
                _json(_collection([{"id": "SV_1"}, {"id": "SV_2"}, {"id": "SV_3"}])),
                _json(_collection([{"QuestionID": "QID9"}])),
            ],
            resume_state=QualtricsResumeConfig(parent_index=2),
        )

        assert result.items == [[{"QuestionID": "QID9", "surveyId": "SV_3"}]]
        assert result.paths[1] == "/API/v3/survey-definitions/SV_3/questions"
        assert result.saved_states == [QualtricsResumeConfig(parent_index=3)]

    @pytest.mark.parametrize(
        "endpoint, resume_state, script, expected_items, expected_paths",
        [
            (
                "directory_contacts",
                QualtricsResumeConfig(
                    parent_index=1,
                    parent_id="POOL_2",
                    child_next_page=f"{BASE}/directories/POOL_2/contacts?skipToken=b",
                ),
                [
                    _json(_collection([{"directoryId": "POOL_1"}, {"directoryId": "POOL_2"}])),
                    _json(_collection([{"contactId": "CID_9"}])),
                ],
                [[{"contactId": "CID_9", "directoryId": "POOL_2"}]],
                ["/API/v3/directories", "/API/v3/directories/POOL_2/contacts"],
            ),
            (
                "directory_contacts",
                QualtricsResumeConfig(
                    parent_index=1,
                    parent_id="POOL_9",
                    child_next_page=f"{BASE}/directories/POOL_9/contacts?skipToken=b",
                ),
                [
                    _json(_collection([{"directoryId": "POOL_1"}, {"directoryId": "POOL_2"}])),
                    _json(_collection([{"contactId": "CID_1"}])),
                ],
                [[{"contactId": "CID_1", "directoryId": "POOL_2"}]],
                ["/API/v3/directories", "/API/v3/directories/POOL_2/contacts"],
            ),
            (
                "distribution_history",
                QualtricsResumeConfig(
                    parent_index=0,
                    parent_id="SV_1",
                    child_id="EMD_2",
                    child_next_page=f"{BASE}/distributions/EMD_2/history?skipToken=b",
                ),
                [
                    _json(_collection([{"id": "SV_1"}])),
                    _json(_collection([{"id": "EMD_1"}, {"id": "EMD_2"}, {"id": "EMD_3"}])),
                    _json(_collection([{"contactId": "CID_5"}])),
                    _json(_collection([{"contactId": "CID_6"}])),
                ],
                [
                    [{"contactId": "CID_5", "surveyId": "SV_1", "distributionId": "EMD_2"}],
                    [{"contactId": "CID_6", "surveyId": "SV_1", "distributionId": "EMD_3"}],
                ],
                [
                    "/API/v3/surveys",
                    "/API/v3/distributions",
                    "/API/v3/distributions/EMD_2/history",
                    "/API/v3/distributions/EMD_3/history",
                ],
            ),
            (
                "distribution_history",
                QualtricsResumeConfig(parent_index=0, parent_id="SV_1", child_id="EMD_1"),
                [
                    _json(_collection([{"id": "SV_1"}])),
                    _json(_collection([{"id": "EMD_1"}, {"id": "EMD_2"}])),
                    _json(_collection([{"contactId": "CID_7"}])),
                ],
                [[{"contactId": "CID_7", "surveyId": "SV_1", "distributionId": "EMD_2"}]],
                ["/API/v3/surveys", "/API/v3/distributions", "/API/v3/distributions/EMD_2/history"],
            ),
        ],
    )
    def test_full_refresh_fanout_resumes_after_the_last_written_page(
        self,
        endpoint: str,
        resume_state: QualtricsResumeConfig,
        script: list[ScriptedResponse],
        expected_items: list[list[dict[str, Any]]],
        expected_paths: list[str],
    ) -> None:
        result = _drive(endpoint, script, resume_state=resume_state)

        assert result.raised is None
        assert result.items == expected_items
        assert result.paths == expected_paths
        expected_token = "b" if resume_state.child_next_page and resume_state.parent_id != "POOL_9" else None
        assert result.params("skipToken")[len(expected_paths) - len(expected_items)] == expected_token


class TestResponseExport:
    NDJSON = "\n".join(
        [
            json.dumps(
                {
                    "responseId": "R_1",
                    "values": {"recordedDate": "2026-01-02T03:04:05Z", "finished": 1, "QID1": 3},
                    "labels": {"QID1": "Often"},
                    "displayedFields": ["QID1"],
                    "displayedValues": {"QID1": [1, 2, 3]},
                }
            ),
            json.dumps({"responseId": "R_2", "values": {"recordedDate": "2026-01-03T03:04:05Z"}}),
        ]
    )

    def _export_script(self, file_body: bytes) -> list[ScriptedResponse | BaseException]:
        return [
            _json(_collection([{"id": "SV_1"}])),
            _json({"result": {"progressId": "PID_1"}}),
            _json({"result": {"status": "inProgress", "percentComplete": 12.5}}),
            _json({"result": {"status": "complete", "fileId": "FID_1"}}),
            ScriptedResponse(body=file_body),
        ]

    def _run(self, script: Script, **inputs: Any) -> DriveResult:
        return _drive("survey_responses", script, **inputs)

    def test_incremental_runs_send_the_watermark_as_start_date(self) -> None:
        result = self._run(
            self._export_script(_zip_bytes("responses.ndjson", self.NDJSON)),
            incremental_field="recordedDate",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        created = [request for request in result.requests if request.method == "POST"]
        assert [request.json() for request in created] == [
            {"format": "ndjson", "compress": True, "startDate": "2026-01-01T00:00:00Z"}
        ]
        assert [row["responseId"] for row in result.rows] == ["R_1", "R_2"]

    @pytest.mark.parametrize(
        "progress_payload",
        [
            {"result": {"status": "failed"}},
            {"result": {"status": "complete"}},
        ],
    )
    def test_a_broken_export_job_fails_permanently(self, progress_payload: dict[str, Any]) -> None:
        result = self._run(
            [
                _json(_collection([{"id": "SV_1"}])),
                _json({"result": {"progressId": "PID_1"}}),
                _json(progress_payload),
            ]
        )

        assert isinstance(result.raised, QualtricsExportFailedError)
        assert EXPORT_FAILED_ERROR in str(result.raised)

    def test_a_missing_progress_id_fails_permanently(self) -> None:
        result = self._run([_json(_collection([{"id": "SV_1"}])), _json({"result": {}})])

        assert isinstance(result.raised, QualtricsExportFailedError)
        assert EXPORT_FAILED_ERROR in str(result.raised)

    def test_blank_lines_in_the_export_are_skipped(self) -> None:
        body = f"\n{self.NDJSON}\n\n"
        rows: list[dict[str, Any]] = list(_iter_export_file(_response(body=body.encode())))

        assert [row["responseId"] for row in rows] == ["R_1", "R_2"]

    def test_decompressed_export_is_capped(self) -> None:
        with mock.patch.object(qualtrics_module, "MAX_EXPORT_DECOMPRESSED_BYTES", 4):
            with pytest.raises(QualtricsResponseTooLargeError):
                list(_iter_export_file(_response(body=_zip_bytes("r.ndjson", self.NDJSON))))

    def test_decompressed_cap_is_shared_across_archive_members(self) -> None:
        # Each member stays under the cap; only their aggregate exceeds it, so a per-member
        # counter would let the archive through.
        body = _multi_member_zip_bytes({"a.ndjson": self.NDJSON, "b.ndjson": self.NDJSON})
        with mock.patch.object(qualtrics_module, "MAX_EXPORT_DECOMPRESSED_BYTES", len(self.NDJSON) + 5):
            with pytest.raises(QualtricsResponseTooLargeError):
                list(_iter_export_file(_response(body=body)))

    def test_archive_with_too_many_members_is_refused(self) -> None:
        # The central-directory byte length is rejected before zipfile builds a ZipInfo per
        # entry, so a crafted many-membered archive can't exhaust memory first.
        body = _multi_member_zip_bytes({f"m_{i}.ndjson": self.NDJSON for i in range(3)})
        with mock.patch.object(qualtrics_module, "MAX_EXPORT_ARCHIVE_MEMBERS", 2):
            with pytest.raises(QualtricsResponseTooLargeError):
                list(_iter_export_file(_response(body=body)))

    def test_archive_with_spoofed_low_member_count_is_refused(self) -> None:
        # A trailing EOCD claiming one member can't hide a large central directory: the guard
        # bounds the directory's byte length, which is what zipfile actually reads.
        body = _zip_with_spoofed_low_member_count({f"m_{i}.ndjson": self.NDJSON for i in range(3)})
        with mock.patch.object(qualtrics_module, "MAX_EXPORT_ARCHIVE_MEMBERS", 2):
            with pytest.raises(QualtricsResponseTooLargeError):
                list(_iter_export_file(_response(body=body)))

    def test_export_batches_flush_on_accumulated_bytes(self) -> None:
        rows = "\n".join(json.dumps({"responseId": f"R_{i}", "values": {"blob": "x" * 500}}) for i in range(3))
        script = self._export_script(_zip_bytes("responses.ndjson", rows))

        with mock.patch.object(qualtrics_module, "MAX_EXPORT_BATCH_BYTES", 400):
            result = self._run(script)

        # Each row's blob column alone exceeds the byte cap, so batches flush per row despite the
        # far larger row-count batch size.
        assert [len(batch) for batch in result.items] == [1, 1, 1]


class TestValidateCredentials:
    def _validate(self, response: ScriptedResponse, schema_name: str | None = None) -> tuple[bool, str | None]:
        with scripted_network([response]):
            return validate_credentials("iad1", API_TOKEN_CREDENTIALS, "v3", schema_name, team_id=1)

    def test_a_working_token_validates(self) -> None:
        assert self._validate(_json({"result": {"brandId": "acme"}})) == (True, None)

    def test_an_invalid_token_is_rejected(self) -> None:
        valid, error = self._validate(_json({}, status=401))
        assert valid is False
        assert error == "Invalid Qualtrics credentials"

    def test_a_403_at_source_create_still_validates(self) -> None:
        # Qualtrics grants permissions per resource, so a user who can't read one endpoint
        # must still be able to connect and sync the ones they can.
        assert self._validate(_json({}, status=403)) == (True, None)

    def test_a_403_on_a_scoped_probe_is_rejected(self) -> None:
        valid, error = self._validate(_json({}, status=403), schema_name="users")
        assert valid is False
        assert error is not None and "users" in error

    @pytest.mark.parametrize("datacenter_id", ["", "   ", "not a host", "iad1.qualtrics.com:8080", "iad1@evil"])
    def test_an_invalid_datacenter_id_is_rejected_before_any_request(self, datacenter_id: str) -> None:
        with scripted_network([]) as network:
            valid, error = validate_credentials(datacenter_id, API_TOKEN_CREDENTIALS, "v3", None, team_id=1)

        assert (valid, error) == (False, "Invalid Qualtrics datacenter ID")
        assert network.requests_log == []
        assert network.session_options == []

    def test_a_blocked_host_is_rejected(self) -> None:
        with mock.patch.object(qualtrics_module, "_is_host_safe", return_value=(False, "nope")):
            valid, error = validate_credentials("iad1", API_TOKEN_CREDENTIALS, "v3", None, team_id=1)
        assert (valid, error) == (False, "nope")


class TestSourceResponse:
    def test_items_are_lazy_so_no_request_happens_until_iterated(self) -> None:
        source = QualtricsSource()
        inputs = source_inputs("users")
        with scripted_network([_json(_collection([{"id": "UR_1"}]))]) as network:
            response = source.source_for_pipeline(_config(), source.get_resumable_source_manager(inputs), inputs)

            assert network.requests_log == []

            items: Iterator[Any] = iter(cast("Iterable[Any]", response.items()))
            assert next(items) == [{"id": "UR_1"}]
            assert len(network.requests_log) == 1

    def test_an_unsafe_host_stops_the_sync(self) -> None:
        with mock.patch.object(qualtrics_module, "_is_host_safe", return_value=(False, "blocked")):
            result = _drive("users", [])

        assert isinstance(result.raised, QualtricsHostNotAllowedError)
        assert result.requests == []
