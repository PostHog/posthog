import io
import json
import zipfile
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
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
    _normalize_response_row,
    _read_capped,
    format_incremental_value,
    get_rows,
    normalize_host,
    qualtrics_source,
    validate_credentials,
    validate_host,
)

HOST = "iad1.qualtrics.com"
BASE = f"https://{HOST}/API/v3"
API_TOKEN_CREDENTIALS = QualtricsCredentials(method="api_token", api_token="tok-123")
OAUTH_CREDENTIALS = QualtricsCredentials(method="oauth_client_credentials", client_id="client", client_secret="shhh")


class FakeResumeManager(ResumableSourceManager[QualtricsResumeConfig]):
    def __init__(self, state: QualtricsResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[QualtricsResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> QualtricsResumeConfig | None:
        return self.state

    def save_state(self, data: QualtricsResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.state = None


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


def _run_get_rows(
    endpoint: str,
    session: mock.MagicMock,
    manager: FakeResumeManager,
    **kwargs: Any,
) -> list[list[dict[str, Any]]]:
    with (
        mock.patch.object(qualtrics_module, "make_tracked_session", return_value=session),
        mock.patch.object(qualtrics_module, "_is_host_safe", return_value=(True, None)),
    ):
        return list(
            get_rows(
                host=HOST,
                credentials=API_TOKEN_CREDENTIALS,
                endpoint=endpoint,
                api_version="v3",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=1,
                **kwargs,
            )
        )


class TestQualtricsTransport:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("iad1", "iad1.qualtrics.com"),
            ("IAD1", "iad1.qualtrics.com"),
            ("  fra1  ", "fra1.qualtrics.com"),
            ("iad1.qualtrics.com", "iad1.qualtrics.com"),
            ("https://iad1.qualtrics.com", "iad1.qualtrics.com"),
            ("https://iad1.qualtrics.com/API/v3/", "iad1.qualtrics.com"),
            ("surveys.acme.com", "surveys.acme.com"),
        ],
    )
    def test_normalize_host(self, raw: str, expected: str) -> None:
        assert normalize_host(raw) == expected

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

    def test_api_token_rides_the_header(self) -> None:
        manager = QualtricsAuthManager(_session(), HOST, API_TOKEN_CREDENTIALS)
        assert manager.headers()["X-API-TOKEN"] == "tok-123"

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

    def test_oauth_token_is_reminted_inside_the_refresh_margin(self) -> None:
        # 30s of life is inside TOKEN_REFRESH_MARGIN_SECONDS, so the next request must not
        # ride a token that would expire mid-flight.
        session = _session(
            post_responses=[
                _response(json_data={"access_token": "first", "expires_in": 30}),
                _response(json_data={"access_token": "second", "expires_in": 3600}),
            ]
        )
        manager = QualtricsAuthManager(session, HOST, OAUTH_CREDENTIALS)

        assert manager.headers()["Authorization"] == "Bearer first"
        assert manager.headers()["Authorization"] == "Bearer second"

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
        with mock.patch.object(qualtrics_module, "make_tracked_session", return_value=_session()):
            client = QualtricsClient(HOST, API_TOKEN_CREDENTIALS, "v3")
        with pytest.raises(QualtricsHostNotAllowedError):
            client.get_json(url)

    def test_client_builds_versioned_urls(self) -> None:
        with mock.patch.object(qualtrics_module, "make_tracked_session", return_value=_session()):
            client = QualtricsClient(HOST, API_TOKEN_CREDENTIALS, "v3")

        assert client.url("/surveys") == f"{BASE}/surveys"
        assert client.url("/distributions", {"surveyId": "SV_1"}) == f"{BASE}/distributions?surveyId=SV_1"


class TestCollectionPagination:
    def test_follows_next_page_and_checkpoints_after_each_page(self) -> None:
        page_two = f"{BASE}/users?offset=100"
        session = _session(
            get_responses=[
                _response(json_data=_collection([{"id": "UR_1"}], next_page=page_two)),
                _response(json_data=_collection([{"id": "UR_2"}], next_page=None)),
            ]
        )
        manager = FakeResumeManager()

        batches = _run_get_rows("users", session, manager)

        assert batches == [[{"id": "UR_1"}], [{"id": "UR_2"}]]
        # Checkpointed only after the first page was yielded, and never past the final page.
        assert manager.saved == [QualtricsResumeConfig(next_page=page_two)]

    def test_resumes_from_the_saved_next_page(self) -> None:
        resume_url = f"{BASE}/users?offset=200"
        session = _session(get_responses=[_response(json_data=_collection([{"id": "UR_9"}]))])

        batches = _run_get_rows("users", session, FakeResumeManager(QualtricsResumeConfig(next_page=resume_url)))

        assert batches == [[{"id": "UR_9"}]]
        assert session.get.call_args.args[0] == resume_url

    def test_empty_collection_yields_nothing(self) -> None:
        session = _session(get_responses=[_response(json_data=_collection([]))])

        assert _run_get_rows("groups", session, FakeResumeManager()) == []

    def test_pagination_that_never_terminates_is_capped(self) -> None:
        session = _session()
        session.get.return_value = _response(json_data=_collection([{"id": "UR_1"}], next_page=f"{BASE}/users?p=1"))

        with mock.patch.object(qualtrics_module, "MAX_PAGES", 3), pytest.raises(QualtricsPaginationLimitError):
            _run_get_rows("users", session, FakeResumeManager())


class TestSurveyFanout:
    def test_query_fanout_stamps_the_parent_survey_id(self) -> None:
        session = _session(
            get_responses=[
                _response(json_data=_collection([{"id": "SV_1"}, {"id": "SV_2"}])),
                _response(json_data=_collection([{"id": "EMD_1"}])),
                _response(json_data=_collection([{"id": "EMD_2"}])),
            ]
        )
        manager = FakeResumeManager()

        batches = _run_get_rows("distributions", session, manager)

        assert batches == [
            [{"id": "EMD_1", "surveyId": "SV_1"}],
            [{"id": "EMD_2", "surveyId": "SV_2"}],
        ]
        assert manager.saved == [QualtricsResumeConfig(parent_index=1), QualtricsResumeConfig(parent_index=2)]

    def test_survey_ids_that_could_steer_the_url_are_dropped(self) -> None:
        session = _session(
            get_responses=[
                _response(json_data=_collection([{"id": "../../oauth2/token"}, {"id": "SV_ok"}])),
                _response(json_data=_collection([{"QuestionID": "QID1"}])),
            ]
        )

        batches = _run_get_rows("survey_questions", session, FakeResumeManager())

        assert batches == [[{"QuestionID": "QID1", "surveyId": "SV_ok"}]]
        assert session.get.call_args_list[1].args[0] == f"{BASE}/survey-definitions/SV_ok/questions"

    def test_over_length_survey_ids_are_dropped(self) -> None:
        session = _session(
            get_responses=[
                _response(json_data=_collection([{"id": "SV_toolong"}, {"id": "SV_ok"}])),
                _response(json_data=_collection([{"QuestionID": "QID1"}])),
            ]
        )

        with mock.patch.object(qualtrics_module, "MAX_SURVEY_ID_LENGTH", 5):
            batches = _run_get_rows("survey_questions", session, FakeResumeManager())

        assert batches == [[{"QuestionID": "QID1", "surveyId": "SV_ok"}]]

    def test_too_many_surveys_is_refused(self) -> None:
        session = _session(get_responses=[_response(json_data=_collection([{"id": "SV_1"}, {"id": "SV_2"}]))])

        with mock.patch.object(qualtrics_module, "MAX_SURVEY_COUNT", 1):
            with pytest.raises(QualtricsResponseTooLargeError):
                _run_get_rows("survey_questions", session, FakeResumeManager())

    def test_path_fanout_stamps_the_parent_survey_id(self) -> None:
        session = _session(
            get_responses=[
                _response(json_data=_collection([{"id": "SV_1"}])),
                _response(json_data=_collection([{"QuestionID": "QID1"}])),
            ]
        )

        batches = _run_get_rows("survey_questions", session, FakeResumeManager())

        assert batches == [[{"QuestionID": "QID1", "surveyId": "SV_1"}]]
        assert session.get.call_args_list[1].args[0] == f"{BASE}/survey-definitions/SV_1/questions"

    def test_resumes_after_the_last_completed_survey(self) -> None:
        session = _session(
            get_responses=[
                _response(json_data=_collection([{"id": "SV_1"}, {"id": "SV_2"}, {"id": "SV_3"}])),
                _response(json_data=_collection([{"QuestionID": "QID9"}])),
            ]
        )
        manager = FakeResumeManager(QualtricsResumeConfig(parent_index=2))

        batches = _run_get_rows("survey_questions", session, manager)

        assert batches == [[{"QuestionID": "QID9", "surveyId": "SV_3"}]]
        assert session.get.call_args_list[1].args[0] == f"{BASE}/survey-definitions/SV_3/questions"
        assert manager.saved == [QualtricsResumeConfig(parent_index=3)]


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

    def _export_session(self, file_body: bytes, start_date_capture: list[Any] | None = None) -> mock.MagicMock:
        session = _session(
            get_responses=[
                _response(json_data=_collection([{"id": "SV_1"}])),
                _response(json_data={"result": {"status": "inProgress", "percentComplete": 12.5}}),
                _response(json_data={"result": {"status": "complete", "fileId": "FID_1"}}),
                _response(body=file_body),
            ],
            post_responses=[_response(json_data={"result": {"progressId": "PID_1"}})],
        )
        if start_date_capture is not None:
            original = session.post.side_effect

            def _capture(url: str, **kwargs: Any) -> Any:
                start_date_capture.append(kwargs.get("json"))
                return next(iter(original))

            session.post.side_effect = _capture
        return session

    def _run(self, session: mock.MagicMock, **kwargs: Any) -> list[list[dict[str, Any]]]:
        with mock.patch.object(qualtrics_module, "EXPORT_POLL_INTERVAL_SECONDS", 0):
            return _run_get_rows("survey_responses", session, FakeResumeManager(), **kwargs)

    def test_polls_until_complete_then_streams_the_zipped_export(self) -> None:
        batches = self._run(self._export_session(_zip_bytes("responses.ndjson", self.NDJSON)))

        assert len(batches) == 1
        rows = batches[0]
        assert [row["responseId"] for row in rows] == ["R_1", "R_2"]
        assert rows[0]["surveyId"] == "SV_1"
        assert rows[0]["recordedDate"] == "2026-01-02T03:04:05Z"
        assert json.loads(rows[0]["labels"]) == {"QID1": "Often"}

    def test_an_uncompressed_export_body_is_parsed_directly(self) -> None:
        batches = self._run(self._export_session(self.NDJSON.encode()))

        assert [row["responseId"] for row in batches[0]] == ["R_1", "R_2"]

    def test_incremental_runs_send_the_watermark_as_start_date(self) -> None:
        captured: list[Any] = []
        session = self._export_session(_zip_bytes("responses.ndjson", self.NDJSON), start_date_capture=captured)

        self._run(
            session,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert captured == [{"format": "ndjson", "compress": True, "startDate": "2026-01-01T00:00:00Z"}]

    def test_full_refresh_runs_send_no_start_date(self) -> None:
        captured: list[Any] = []
        session = self._export_session(_zip_bytes("responses.ndjson", self.NDJSON), start_date_capture=captured)

        self._run(session)

        assert captured == [{"format": "ndjson", "compress": True}]

    @pytest.mark.parametrize(
        "progress_payload",
        [
            {"result": {"status": "failed"}},
            {"result": {"status": "complete"}},
        ],
    )
    def test_a_broken_export_job_fails_permanently(self, progress_payload: dict[str, Any]) -> None:
        session = _session(
            get_responses=[
                _response(json_data=_collection([{"id": "SV_1"}])),
                _response(json_data=progress_payload),
            ],
            post_responses=[_response(json_data={"result": {"progressId": "PID_1"}})],
        )

        with pytest.raises(QualtricsExportFailedError, match=EXPORT_FAILED_ERROR):
            self._run(session)

    def test_a_missing_progress_id_fails_permanently(self) -> None:
        session = _session(
            get_responses=[_response(json_data=_collection([{"id": "SV_1"}]))],
            post_responses=[_response(json_data={"result": {}})],
        )

        with pytest.raises(QualtricsExportFailedError, match=EXPORT_FAILED_ERROR):
            self._run(session)

    def test_export_rows_are_batched(self) -> None:
        many = "\n".join(json.dumps({"responseId": f"R_{i}", "values": {}}) for i in range(5))
        session = self._export_session(_zip_bytes("responses.ndjson", many))

        with mock.patch.object(qualtrics_module, "EXPORT_BATCH_SIZE", 2):
            batches = self._run(session)

        assert [len(batch) for batch in batches] == [2, 2, 1]

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
        session = self._export_session(_zip_bytes("responses.ndjson", rows))

        with mock.patch.object(qualtrics_module, "MAX_EXPORT_BATCH_BYTES", 400):
            batches = self._run(session)

        # Each row's blob column alone exceeds the byte cap, so batches flush per row despite the
        # far larger row-count batch size.
        assert [len(batch) for batch in batches] == [1, 1, 1]


class TestNormalizeResponseRow:
    def test_flattens_values_and_json_encodes_the_survey_specific_blobs(self) -> None:
        row = _normalize_response_row(
            "SV_1",
            {
                "responseId": "R_1",
                "values": {
                    "recordedDate": "2026-01-02T03:04:05Z",
                    "startDate": "2026-01-02T03:00:00Z",
                    "progress": 100,
                    "duration": 42,
                    "finished": 1,
                    "QID1": 3,
                },
                "labels": {"QID1": "Often"},
            },
        )

        assert row["surveyId"] == "SV_1"
        assert row["responseId"] == "R_1"
        assert row["progress"] == 100
        assert json.loads(row["values"])["QID1"] == 3
        assert json.loads(row["displayedFields"]) == []

    def test_falls_back_to_the_record_id_when_the_response_id_is_absent(self) -> None:
        row = _normalize_response_row("SV_1", {"values": {"_recordId": "R_7"}})

        assert row["responseId"] == "R_7"


class TestValidateCredentials:
    def _validate(self, response: mock.MagicMock, schema_name: str | None = None) -> tuple[bool, str | None]:
        with (
            mock.patch.object(qualtrics_module, "make_tracked_session", return_value=_session([response])),
            mock.patch.object(qualtrics_module, "_is_host_safe", return_value=(True, None)),
        ):
            return validate_credentials("iad1", API_TOKEN_CREDENTIALS, "v3", schema_name, team_id=1)

    def test_a_working_token_validates(self) -> None:
        assert self._validate(_response(json_data={"result": {"brandId": "acme"}})) == (True, None)

    def test_an_invalid_token_is_rejected(self) -> None:
        valid, error = self._validate(_response(status_code=401))
        assert valid is False
        assert error == "Invalid Qualtrics credentials"

    def test_a_403_at_source_create_still_validates(self) -> None:
        # Qualtrics grants permissions per resource, so a user who can't read one endpoint
        # must still be able to connect and sync the ones they can.
        assert self._validate(_response(status_code=403)) == (True, None)

    def test_a_403_on_a_scoped_probe_is_rejected(self) -> None:
        valid, error = self._validate(_response(status_code=403), schema_name="users")
        assert valid is False
        assert error is not None and "users" in error

    @pytest.mark.parametrize("datacenter_id", ["", "   ", "not a host", "iad1.qualtrics.com:8080", "iad1@evil"])
    def test_an_invalid_datacenter_id_is_rejected_before_any_request(self, datacenter_id: str) -> None:
        with mock.patch.object(qualtrics_module, "make_tracked_session") as session_factory:
            valid, error = validate_credentials(datacenter_id, API_TOKEN_CREDENTIALS, "v3", None, team_id=1)

        assert (valid, error) == (False, "Invalid Qualtrics datacenter ID")
        assert session_factory.call_count == 0

    def test_a_blocked_host_is_rejected(self) -> None:
        with mock.patch.object(qualtrics_module, "_is_host_safe", return_value=(False, "nope")):
            valid, error = validate_credentials("iad1", API_TOKEN_CREDENTIALS, "v3", None, team_id=1)
        assert (valid, error) == (False, "nope")

    def test_fanout_endpoints_probe_the_survey_list(self) -> None:
        session = _session([_response(json_data=_collection([]))])
        with (
            mock.patch.object(qualtrics_module, "make_tracked_session", return_value=session),
            mock.patch.object(qualtrics_module, "_is_host_safe", return_value=(True, None)),
        ):
            validate_credentials("iad1", API_TOKEN_CREDENTIALS, "v3", "survey_responses", team_id=1)

        assert session.get.call_args.args[0] == f"{BASE}/surveys"


class TestSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, sort_mode, partition_keys",
        [
            ("surveys", ["id"], "asc", ["creationDate"]),
            ("users", ["id"], "asc", None),
            ("groups", ["id"], "asc", None),
            ("divisions", ["divisionId"], "asc", None),
            ("distributions", ["surveyId", "id"], "desc", None),
            ("survey_questions", ["surveyId", "QuestionID"], "desc", None),
            ("survey_responses", ["surveyId", "responseId"], "desc", ["recordedDate"]),
        ],
    )
    def test_response_shape_per_endpoint(
        self,
        endpoint: str,
        primary_keys: list[str],
        sort_mode: str,
        partition_keys: list[str] | None,
    ) -> None:
        response = qualtrics_source(
            datacenter_id="iad1",
            credentials=API_TOKEN_CREDENTIALS,
            endpoint=endpoint,
            api_version="v3",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
            team_id=1,
        )

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)

    def test_items_are_lazy_so_no_request_happens_until_iterated(self) -> None:
        session = _session(get_responses=[_response(json_data=_collection([{"id": "UR_1"}]))])
        response = qualtrics_source(
            datacenter_id="iad1",
            credentials=API_TOKEN_CREDENTIALS,
            endpoint="users",
            api_version="v3",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
            team_id=1,
        )

        assert session.get.call_count == 0

        with (
            mock.patch.object(qualtrics_module, "make_tracked_session", return_value=session),
            mock.patch.object(qualtrics_module, "_is_host_safe", return_value=(True, None)),
        ):
            items: Iterator[Any] = iter(cast("Iterable[Any]", response.items()))
            assert next(items) == [{"id": "UR_1"}]

    def test_an_unsafe_host_stops_the_sync(self) -> None:
        response = qualtrics_source(
            datacenter_id="iad1",
            credentials=API_TOKEN_CREDENTIALS,
            endpoint="users",
            api_version="v3",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
            team_id=1,
        )

        with mock.patch.object(qualtrics_module, "_is_host_safe", return_value=(False, "blocked")):
            with pytest.raises(QualtricsHostNotAllowedError):
                list(cast("Iterable[Any]", response.items()))
