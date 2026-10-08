from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
import requests_mock
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.persona import persona
from products.warehouse_sources.backend.temporal.data_imports.sources.persona.persona import (
    PERSONA_BASE_URL,
    PersonaRedirectError,
    PersonaResumeConfig,
    PersonaRetryableError,
    _format_datetime_z,
    _to_datetime,
    get_rows,
    persona_source,
)


class _FakeResumableManager:
    def __init__(self, state: PersonaResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PersonaResumeConfig] = []
        self.cleared = 0

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PersonaResumeConfig | None:
        return self._state

    def save_state(self, data: PersonaResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared += 1


class TestFormatDatetimeZ:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("microseconds", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            ("naive_treated_as_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
        ]
    )
    def test_format(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_datetime_z(value) == expected


class TestToDatetime:
    @parameterized.expand(
        [
            ("iso_z_string", "2026-01-15T10:30:45.000Z", datetime(2026, 1, 15, 10, 30, 45, tzinfo=UTC)),
            ("aware_datetime", datetime(2026, 1, 15, tzinfo=UTC), datetime(2026, 1, 15, tzinfo=UTC)),
            ("date_value", date(2026, 1, 15), datetime(2026, 1, 15, tzinfo=UTC)),
        ]
    )
    def test_parses(self, _name: str, value: Any, expected: datetime) -> None:
        assert _to_datetime(value) == expected

    @parameterized.expand([("none", None), ("garbage", "not-a-date")])
    def test_unparseable_returns_none(self, _name: str, value: Any) -> None:
        assert _to_datetime(value) is None


class TestFetchPageRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        # 429 / 5xx are transient — they must raise the retryable type so tenacity retries them.
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(PersonaRetryableError):
            persona._fetch_page(session, "https://api.withpersona.com/api/v1/inquiries", {}, MagicMock())
        # tenacity retries 5 times before giving up.
        assert session.get.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_immediately(self, _name: str, status: int) -> None:
        # Auth/permission errors can never be fixed by retrying, so they must surface at once.
        response = requests.Response()
        response.status_code = status
        response.url = "https://api.withpersona.com/api/v1/inquiries"
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            persona._fetch_page(session, "https://api.withpersona.com/api/v1/inquiries", {}, MagicMock())
        assert session.get.call_count == 1


class TestRedirectsRefused:
    # The apex host answers a redirected request with a 403 bot challenge, which must not be read
    # as an auth failure. The session refuses the redirect so the key never leaves the API host.
    API_URL = f"{PERSONA_BASE_URL}/inquiries"
    TARGET_URL = "https://withpersona.com/api/v1/inquiries"

    @parameterized.expand([("moved_permanently", 301), ("found", 302)])
    def test_sync_refuses_redirect_and_keeps_key_on_api_host(self, _name: str, status: int) -> None:
        with requests_mock.Mocker() as m:
            m.get(self.API_URL, status_code=status, headers={"Location": self.TARGET_URL})
            m.get(self.TARGET_URL, status_code=403)

            with pytest.raises(PersonaRedirectError, match="redirected the API request to withpersona.com"):
                list(
                    get_rows(
                        api_key="persona_test",
                        endpoint="inquiries",
                        logger=MagicMock(),
                        resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                    )
                )

            assert [r.hostname for r in m.request_history] == ["api.withpersona.com"]
            assert m.request_history[0].headers["Authorization"] == "Bearer persona_test"

    def test_validate_credentials_returns_the_redirect_status_without_following(self) -> None:
        with requests_mock.Mocker() as m:
            m.get(self.API_URL, status_code=302, headers={"Location": self.TARGET_URL})
            m.get(self.TARGET_URL, status_code=403)

            assert persona.validate_credentials("persona_test") == 302
            assert [r.hostname for r in m.request_history] == ["api.withpersona.com"]


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    pages: list[dict],
    endpoint: str = "inquiries",
    **kwargs: Any,
) -> list[dict]:
    """Feed canned pages to get_rows in order and return the flattened rows."""
    calls: list[str] = []
    iterator = iter(pages)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        calls.append(url)
        return next(iterator)

    monkeypatch.setattr(persona, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_key="persona_test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(table.to_pylist())
    manager.fetched_urls = calls  # type: ignore[attr-defined]
    return rows


class TestIncrementalWatermarkGuard:
    def test_stops_once_rows_predate_watermark(self, monkeypatch: Any) -> None:
        # Guards against re-walking full history: even though links.next is present, once a row older
        # than the watermark appears (newest-first ordering) we stop and never fetch the next page.
        pages = [
            {
                "data": [
                    {"type": "inquiry", "id": "inq_new", "attributes": {"created-at": "2026-01-20T00:00:00.000Z"}},
                    {"type": "inquiry", "id": "inq_old", "attributes": {"created-at": "2026-01-05T00:00:00.000Z"}},
                ],
                "links": {"next": "/api/v1/inquiries?page[after]=inq_old"},
            },
            {"data": [{"type": "inquiry", "id": "inq_never"}], "links": {"next": None}},
        ]
        manager = _FakeResumableManager()
        rows = _collect(
            manager,
            monkeypatch,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
        )

        assert [r["id"] for r in rows] == ["inq_new"]
        assert len(manager.fetched_urls) == 1  # type: ignore[attr-defined]


class TestResume:
    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(state=PersonaResumeConfig(after="inq_saved"))
        _collect(manager, monkeypatch, [{"data": [], "links": {"next": None}}])
        # First request on resume must carry the saved page[after] cursor.
        assert "page[after]=inq_saved" in manager.fetched_urls[0]  # type: ignore[attr-defined]

    def test_keeps_the_cursor_when_the_walk_does_not_finish(self, monkeypatch: Any) -> None:
        # A run cut short by a worker restart must leave its checkpoint behind, so the next attempt
        # resumes mid-window instead of re-walking from the last completed watermark.
        pages = iter(
            [
                {
                    "data": [
                        {"type": "inquiry", "id": "inq_1", "attributes": {"created-at": "2026-01-03T00:00:00.000Z"}}
                    ],
                    "links": {"next": "/api/v1/inquiries?page[after]=inq_1"},
                }
            ]
        )

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            try:
                return next(pages)
            except StopIteration:
                raise PersonaRetryableError("worker went away")

        monkeypatch.setattr(persona, "_fetch_page", fake_fetch)

        manager = _FakeResumableManager()
        with pytest.raises(PersonaRetryableError):
            for _ in get_rows(
                api_key="persona_test",
                endpoint="inquiries",
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            ):
                pass

        assert manager.cleared == 0


def _verifications(count: int, prefix: str) -> list[dict]:
    return [
        {"type": "verification/selfie", "id": f"{prefix}_{index}", "attributes": {"status": "passed"}}
        for index in range(count)
    ]


class TestVerificationsFanout:
    def test_hydrates_each_inquiry_and_tags_rows_with_the_parent(self, monkeypatch: Any) -> None:
        pages = [
            {
                "data": [{"type": "inquiry", "id": "inq_1", "attributes": {"created-at": "2026-01-03T00:00:00.000Z"}}],
                "links": {"next": None},
            },
            {
                "data": {"type": "inquiry", "id": "inq_1", "attributes": {}},
                "included": [
                    {"type": "verification/government-id", "id": "ver_1", "attributes": {"status": "failed"}},
                    {"type": "verification/selfie", "id": "ver_2", "attributes": {"status": "passed"}},
                    # Accounts on an older API version serialize related resources beyond the ones asked
                    # for; only verifications belong in this table.
                    {"type": "account", "id": "act_1", "attributes": {"status": "active"}},
                ],
            },
        ]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, pages, endpoint="verifications")

        assert [r["id"] for r in rows] == ["ver_1", "ver_2"]
        assert [r["status"] for r in rows] == ["failed", "passed"]
        assert {r["inquiry-id"] for r in rows} == {"inq_1"}
        assert {r["inquiry-created-at"] for r in rows} == {"2026-01-03T00:00:00.000Z"}
        # Persona has no cross-inquiry list of verifications and rejects `include` on list endpoints,
        # so each inquiry has to be hydrated on its own.
        assert manager.fetched_urls[1] == "https://api.withpersona.com/api/v1/inquiries/inq_1?include=verifications"  # type: ignore[attr-defined]

    def test_resume_cursor_is_an_inquiry_id_not_a_verification_id(self, monkeypatch: Any) -> None:
        # A `ver_` id is a meaningless `page[after]` on /inquiries, and a cursor that overshoots the
        # inquiry still being batched drops its buffered rows on resume.
        pages: list[dict[str, Any]] = [
            {
                "data": [
                    {"type": "inquiry", "id": "inq_a", "attributes": {"created-at": "2026-01-03T00:00:00.000Z"}},
                    {"type": "inquiry", "id": "inq_b", "attributes": {"created-at": "2026-01-02T00:00:00.000Z"}},
                ],
                "links": {"next": "/api/v1/inquiries?page[after]=inq_b"},
            },
            # One row short of the batcher's chunk size, so the flush lands part-way through `inq_b`.
            {"data": {}, "included": _verifications(1999, "vera")},
            {"data": {}, "included": _verifications(2, "verb")},
            {"data": [], "links": {"next": None}},
        ]
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages, endpoint="verifications")

        assert [state.after for state in manager.saved] == ["inq_a"]

    def test_hydrate_404_skips_parent_instead_of_aborting_the_sync(self, monkeypatch: Any) -> None:
        # An inquiry can be redacted/deleted between the list page and this hydrate call. Without a
        # 404 guard, that fetch raises and kills the whole generator, and since the checkpoint only
        # advances after an item's rows are processed, a resume re-fetches the same gone inquiry
        # forever instead of moving on to the rest.
        calls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            calls.append(url)
            if "/inquiries/inq_gone" in url:
                response = requests.Response()
                response.status_code = 404
                raise requests.HTTPError(response=response)
            if "/inquiries/inq_ok" in url:
                return {
                    "data": {"type": "inquiry", "id": "inq_ok", "attributes": {}},
                    "included": [{"type": "verification/selfie", "id": "ver_1", "attributes": {"status": "passed"}}],
                }
            return {
                "data": [
                    {"type": "inquiry", "id": "inq_gone", "attributes": {"created-at": "2026-01-03T00:00:00.000Z"}},
                    {"type": "inquiry", "id": "inq_ok", "attributes": {"created-at": "2026-01-02T00:00:00.000Z"}},
                ],
                "links": {"next": None},
            }

        monkeypatch.setattr(persona, "_fetch_page", fake_fetch)
        manager = _FakeResumableManager()

        rows: list[dict] = []
        for table in get_rows(
            api_key="persona_test",
            endpoint="verifications",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(table.to_pylist())

        assert [r["id"] for r in rows] == ["ver_1"]
        assert calls == [
            "https://api.withpersona.com/api/v1/inquiries?page[size]=100",
            "https://api.withpersona.com/api/v1/inquiries/inq_gone?include=verifications",
            "https://api.withpersona.com/api/v1/inquiries/inq_ok?include=verifications",
        ]

    def test_hydrate_non_404_error_still_aborts_the_sync(self, monkeypatch: Any) -> None:
        # Only a 404 (gone parent) is safe to swallow. A 500 or any other failure must still surface,
        # not get silently treated the same as a deleted inquiry.
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            if "/inquiries/inq_1" in url:
                response = requests.Response()
                response.status_code = 500
                raise requests.HTTPError(response=response)
            return {
                "data": [{"type": "inquiry", "id": "inq_1", "attributes": {"created-at": "2026-01-03T00:00:00.000Z"}}],
                "links": {"next": None},
            }

        monkeypatch.setattr(persona, "_fetch_page", fake_fetch)
        manager = _FakeResumableManager()

        with pytest.raises(requests.HTTPError):
            list(
                get_rows(
                    api_key="persona_test",
                    endpoint="verifications",
                    logger=MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )


def _template_page(*ids: str) -> dict:
    return {
        "data": [{"type": "inquiry-template", "id": tid, "attributes": {"status": "active"}} for tid in ids],
        "links": {"next": None},
    }


def _template_version(vid: str, status: str = "published") -> dict:
    return {"type": "inquiry-template-version", "id": vid, "attributes": {"status": status}}


class TestInquiryTemplateVersionsFanout:
    def test_pages_each_templates_versions_and_tags_rows_with_the_template(self, monkeypatch: Any) -> None:
        pages = [
            _template_page("itmpl_a", "itmpl_b"),
            {
                "data": [_template_version("itmplv_a1", "draft"), _template_version("itmplv_a2")],
                "links": {"next": "/api/v1/inquiry-template-versions?page[after]=itmplv_a2"},
            },
            {"data": [_template_version("itmplv_a3")], "links": {"next": None}},
            {"data": [_template_version("itmplv_b1")], "links": {"next": None}},
        ]
        manager = _FakeResumableManager()
        rows = _collect(manager, monkeypatch, pages, endpoint="inquiry_template_versions")

        assert [(r["id"], r["inquiry-template-id"]) for r in rows] == [
            ("itmplv_a1", "itmpl_a"),
            ("itmplv_a2", "itmpl_a"),
            ("itmplv_a3", "itmpl_a"),
            ("itmplv_b1", "itmpl_b"),
        ]
        assert manager.fetched_urls == [  # type: ignore[attr-defined]
            "https://api.withpersona.com/api/v1/inquiry-templates?page[size]=100",
            "https://api.withpersona.com/api/v1/inquiry-template-versions?filter[inquiry-template-id]=itmpl_a&page[size]=100",
            "https://api.withpersona.com/api/v1/inquiry-template-versions?filter[inquiry-template-id]=itmpl_a&page[size]=100&page[after]=itmplv_a2",
            "https://api.withpersona.com/api/v1/inquiry-template-versions?filter[inquiry-template-id]=itmpl_b&page[size]=100",
        ]

    @parameterized.expand([("gone_template_is_skipped", 404, None), ("server_error_aborts", 500, requests.HTTPError)])
    def test_version_list_error_handling(self, _name: str, status: int, expected_error: type[Exception] | None) -> None:
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            if "itmpl_gone" in url:
                response = requests.Response()
                response.status_code = status
                raise requests.HTTPError(response=response)
            if "itmpl_ok" in url:
                return {"data": [_template_version("itmplv_ok")], "links": {"next": None}}
            return _template_page("itmpl_gone", "itmpl_ok")

        manager = _FakeResumableManager()
        with patch.object(persona, "_fetch_page", fake_fetch):
            rows_iter = get_rows(
                api_key="persona_test",
                endpoint="inquiry_template_versions",
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
            if expected_error is not None:
                with pytest.raises(expected_error):
                    list(rows_iter)
                return
            rows = [row for table in rows_iter for row in table.to_pylist()]

        assert [r["id"] for r in rows] == ["itmplv_ok"]


class TestPersonaSourceResponse:
    @parameterized.expand(
        [("inquiries", "created_at"), ("events", "created_at"), ("verifications", "inquiry_created_at")]
    )
    def test_incremental_endpoint_partitions_on_created_at_desc(self, endpoint: str, partition_key: str) -> None:
        response = persona_source(
            api_key="persona_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # sort_mode must be desc — Persona returns newest-first, and the pipeline relies on this to
        # defer the incremental watermark advance to end-of-sync.
        assert response.sort_mode == "desc"
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"

    @parameterized.expand([("inquiry_templates",), ("inquiry_template_versions",)])
    def test_full_refresh_endpoint_has_no_partitioning(self, endpoint: str) -> None:
        response = persona_source(
            api_key="persona_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode is None
        assert response.partition_keys is None
