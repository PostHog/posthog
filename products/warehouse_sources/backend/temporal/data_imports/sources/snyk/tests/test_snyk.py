import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized
from tenacity import stop_after_attempt, wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.snyk import snyk
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.snyk import (
    SNYK_REST_VERSION,
    SnykResumeConfig,
    SnykRetryableError,
    _flatten_item,
    _next_page_url,
    get_rows,
    validate_credentials,
)

HOST = "https://api.snyk.io"


class _FakeResumableManager:
    def __init__(self, state: SnykResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SnykResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SnykResumeConfig | None:
        return self._state

    def save_state(self, data: SnykResumeConfig) -> None:
        self.saved.append(data)


def _make_response(status_code: int, body: Any = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    if body is not None:
        response._content = json.dumps(body).encode()
    return response


class _FakeSession:
    """Returns queued responses in order, recording the URLs requested."""

    def __init__(self, responses: list[requests.Response]) -> None:
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: int | None = None) -> requests.Response:
        self.requested_urls.append(url)
        return self._responses.pop(0)


def _collect(
    endpoint: str,
    pages: Mapping[str, tuple[list[dict], str | None]],
    manager: _FakeResumableManager,
    monkeypatch: Any,
    organization_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> list[dict]:
    monkeypatch.setattr(snyk, "make_tracked_session", lambda *args, **kwargs: MagicMock())

    def fake_fetch_list_page(session: Any, url: str, host: str, logger: Any) -> tuple[list[dict], str | None]:
        if url not in pages:
            raise AssertionError(f"unexpected URL requested: {url}")
        return pages[url]

    monkeypatch.setattr(snyk, "_fetch_list_page", fake_fetch_list_page)

    rows: list[dict] = []
    for batch in get_rows(
        region="us",
        api_token="tok",
        organization_id=organization_id,
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        incremental_field=incremental_field,
    ):
        rows.extend(batch)
    return rows


ORGS_URL = f"{HOST}/rest/orgs?version={SNYK_REST_VERSION}&limit=100"


def _issues_url(org_id: str, extra: str = "") -> str:
    return f"{HOST}/rest/orgs/{org_id}/issues?version={SNYK_REST_VERSION}&limit=100{extra}"


class TestNextPageUrl:
    @parameterized.expand(
        [
            (
                "absolute_same_host",
                {"links": {"next": f"{HOST}/rest/orgs?starting_after=abc"}},
                f"{HOST}/rest/orgs?starting_after=abc",
            ),
            ("absolute_other_host_rejected", {"links": {"next": "https://evil.example.com/rest/orgs"}}, None),
            ("http_scheme_rejected", {"links": {"next": "http://api.snyk.io/rest/orgs?x=1"}}, None),
            (
                "relative_with_rest_prefix",
                {"links": {"next": "/rest/orgs?starting_after=abc"}},
                f"{HOST}/rest/orgs?starting_after=abc",
            ),
            (
                "relative_without_rest_prefix",
                {"links": {"next": "/orgs/o1/issues?starting_after=abc"}},
                f"{HOST}/rest/orgs/o1/issues?starting_after=abc",
            ),
            (
                "relative_without_leading_slash",
                {"links": {"next": "orgs?starting_after=abc"}},
                f"{HOST}/rest/orgs?starting_after=abc",
            ),
            (
                "href_object_form",
                {"links": {"next": {"href": "/rest/orgs?starting_after=abc"}}},
                f"{HOST}/rest/orgs?starting_after=abc",
            ),
            ("no_next", {"links": {"prev": "/rest/orgs"}}, None),
            ("empty_next", {"links": {"next": ""}}, None),
            ("no_links", {"data": []}, None),
            ("non_dict_payload", [], None),
        ]
    )
    def test_next_page_url(self, _name: str, payload: Any, expected: str | None) -> None:
        assert _next_page_url(HOST, payload) == expected


class TestFlattenItem:
    def test_lifts_attributes_keeping_id_and_type(self) -> None:
        item = {
            "id": "i1",
            "type": "issue",
            "attributes": {"title": "XSS", "created_at": "2025-01-01T00:00:00Z"},
            "relationships": {"organization": {"data": {"id": "o1"}}},
        }
        flattened = _flatten_item(item)
        assert flattened["id"] == "i1"
        assert flattened["type"] == "issue"
        assert flattened["title"] == "XSS"
        assert flattened["created_at"] == "2025-01-01T00:00:00Z"
        assert "attributes" not in flattened
        assert flattened["relationships"] == {"organization": {"data": {"id": "o1"}}}

    def test_root_keys_win_over_attribute_collisions(self) -> None:
        # `id`/`type` at the root are the JSON:API identifiers; an attribute with the same name
        # must not clobber them or merge primary keys break.
        item = {"id": "i1", "attributes": {"id": "other", "title": "t"}}
        assert _flatten_item(item)["id"] == "i1"


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        session = _FakeSession([_make_response(status_code) for _ in range(5)])
        fast_fetch = snyk._fetch_page.retry_with(wait=wait_none(), stop=stop_after_attempt(3))  # type: ignore[attr-defined]
        with pytest.raises(SnykRetryableError):
            fast_fetch(session, f"{HOST}/rest/orgs", MagicMock())

    def test_client_error_raises_http_error_without_retry(self) -> None:
        session = _FakeSession([_make_response(401, body={"errors": [{"status": "401"}]})])
        with pytest.raises(requests.HTTPError):
            snyk._fetch_page(session, f"{HOST}/rest/orgs", MagicMock())  # type: ignore[arg-type]
        assert len(session.requested_urls) == 1


class TestTopLevelOrganizations:
    def test_paginates_and_flattens(self, monkeypatch: Any) -> None:
        page2 = f"{HOST}/rest/orgs?version={SNYK_REST_VERSION}&limit=100&starting_after=cursor"
        pages = {
            ORGS_URL: ([{"id": "o1", "type": "org", "attributes": {"name": "Org 1"}}], page2),
            page2: ([{"id": "o2", "type": "org", "attributes": {"name": "Org 2"}}], None),
        }
        rows = _collect("organizations", pages, _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": "o1", "type": "org", "name": "Org 1"},
            {"id": "o2", "type": "org", "name": "Org 2"},
        ]

    def test_saves_state_after_yield_and_resumes_from_it(self, monkeypatch: Any) -> None:
        page2 = f"{HOST}/rest/orgs?version={SNYK_REST_VERSION}&limit=100&starting_after=cursor"
        pages = {
            ORGS_URL: ([{"id": "o1"}], page2),
            page2: ([{"id": "o2"}], None),
        }
        manager = _FakeResumableManager()
        _collect("organizations", pages, manager, monkeypatch)
        assert [s.next_url for s in manager.saved] == [page2]

        resumed = _FakeResumableManager(SnykResumeConfig(next_url=page2))
        rows = _collect("organizations", {page2: ([{"id": "o2"}], None)}, resumed, monkeypatch)
        assert rows == [{"id": "o2"}]

    def test_resume_state_on_wrong_host_is_rejected(self, monkeypatch: Any) -> None:
        # The resume URL is fetched with the auth header attached, so tampered Redis state must
        # not be able to redirect the request off the Snyk host.
        manager = _FakeResumableManager(SnykResumeConfig(next_url="https://evil.example.com/rest/orgs"))
        with pytest.raises(ValueError):
            _collect("organizations", {}, manager, monkeypatch)

    def test_configured_org_fetches_single_org_directly(self, monkeypatch: Any) -> None:
        # A single-org connection must not enumerate every org the token can reach: it fetches
        # /orgs/{org_id} directly and emits only that org. Hitting the /orgs list would raise.
        monkeypatch.setattr(snyk, "make_tracked_session", lambda *args, **kwargs: MagicMock())
        monkeypatch.setattr(
            snyk,
            "_fetch_list_page",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not enumerate orgs")),
        )
        requested: list[str] = []

        def fake_fetch_page(session: Any, url: str, logger: Any) -> Any:
            requested.append(url)
            return {"data": {"id": "o9", "type": "org", "attributes": {"name": "Org 9"}}}

        monkeypatch.setattr(snyk, "_fetch_page", fake_fetch_page)

        rows: list[dict] = []
        for batch in get_rows(
            region="us",
            api_token="tok",
            organization_id="o9",
            endpoint="organizations",
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        ):
            rows.extend(batch)

        assert rows == [{"id": "o9", "type": "org", "name": "Org 9"}]
        assert requested == [f"{HOST}/rest/orgs/o9?version={SNYK_REST_VERSION}"]

    def test_configured_org_id_is_validated_before_the_request(self, monkeypatch: Any) -> None:
        # The org id is interpolated into the URL path, so a path-altering value must be rejected
        # before any request is made — even on the single-org organizations path.
        monkeypatch.setattr(snyk, "make_tracked_session", lambda *args, **kwargs: MagicMock())
        with pytest.raises(ValueError):
            _collect("organizations", {}, _FakeResumableManager(), monkeypatch, organization_id="../self")


class TestPerOrgFanOut:
    def _two_org_pages(self) -> dict[str, tuple[list[dict], str | None]]:
        return {
            ORGS_URL: ([{"id": "o1"}, {"id": "o2"}], None),
            _issues_url("o1"): ([{"id": "i1", "attributes": {"title": "a"}}], None),
            _issues_url("o2"): ([{"id": "i2", "attributes": {"title": "b"}}], None),
        }

    def test_walks_every_org_and_injects_organization_id(self, monkeypatch: Any) -> None:
        rows = _collect("issues", self._two_org_pages(), _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": "i1", "title": "a", "organization_id": "o1"},
            {"id": "i2", "title": "b", "organization_id": "o2"},
        ]

    def test_configured_org_skips_enumeration(self, monkeypatch: Any) -> None:
        # Only the single org's issues URL is served; hitting /orgs would raise in the fake.
        pages = {_issues_url("o9"): ([{"id": "i9"}], None)}
        rows = _collect("issues", pages, _FakeResumableManager(), monkeypatch, organization_id="o9")
        assert rows == [{"id": "i9", "organization_id": "o9"}]

    def test_invalid_configured_org_id_is_rejected(self, monkeypatch: Any) -> None:
        with pytest.raises(ValueError):
            _collect("issues", {}, _FakeResumableManager(), monkeypatch, organization_id="../self")

    def test_saves_org_bookmark_with_next_url(self, monkeypatch: Any) -> None:
        o1_page2 = f"{HOST}/rest/orgs/o1/issues?version={SNYK_REST_VERSION}&starting_after=cursor"
        pages = {
            ORGS_URL: ([{"id": "o1"}], None),
            _issues_url("o1"): ([{"id": "i1"}], o1_page2),
            o1_page2: ([{"id": "i1b"}], None),
        }
        manager = _FakeResumableManager()
        _collect("issues", pages, manager, monkeypatch)
        assert [(s.org_id, s.next_url) for s in manager.saved] == [("o1", o1_page2)]

    def test_resume_skips_already_processed_orgs(self, monkeypatch: Any) -> None:
        # Bookmarked mid-o2: o1 must not be re-fetched (its URL is absent from `pages`, so a fetch
        # would raise); o2 continues from the saved page.
        o2_page2 = f"{HOST}/rest/orgs/o2/issues?version={SNYK_REST_VERSION}&starting_after=cursor"
        pages = {
            ORGS_URL: ([{"id": "o1"}, {"id": "o2"}], None),
            o2_page2: ([{"id": "i2b"}], None),
        }
        manager = _FakeResumableManager(SnykResumeConfig(next_url=o2_page2, org_id="o2"))
        rows = _collect("issues", pages, manager, monkeypatch)
        assert rows == [{"id": "i2b", "organization_id": "o2"}]

    def test_resume_from_removed_org_restarts_from_first(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SnykResumeConfig(next_url=_issues_url("GONE"), org_id="GONE"))
        rows = _collect("issues", self._two_org_pages(), manager, monkeypatch)
        assert [row["id"] for row in rows] == ["i1", "i2"]

    def test_resume_survives_reordered_org_list(self, monkeypatch: Any) -> None:
        # /orgs has no sort param, so the API may return orgs in a different order after a crash.
        # Sorting keeps the positional resume stable: o3 (not yet processed) must not be skipped
        # just because the raw response now lists it before the bookmarked o2, and the already-done
        # o1 must not be re-fetched (its URL is absent, so a fetch would raise).
        o2_page2 = f"{HOST}/rest/orgs/o2/issues?version={SNYK_REST_VERSION}&starting_after=cursor"
        pages = {
            ORGS_URL: ([{"id": "o3"}, {"id": "o2"}, {"id": "o1"}], None),
            o2_page2: ([{"id": "i2b"}], None),
            _issues_url("o3"): ([{"id": "i3"}], None),
        }
        manager = _FakeResumableManager(SnykResumeConfig(next_url=o2_page2, org_id="o2"))
        rows = _collect("issues", pages, manager, monkeypatch)
        assert rows == [
            {"id": "i2b", "organization_id": "o2"},
            {"id": "i3", "organization_id": "o3"},
        ]


class TestIncrementalFilters:
    @parameterized.expand(
        [
            ("default_field", None, "updated_after"),
            ("explicit_updated_at", "updated_at", "updated_after"),
            ("created_at_maps_to_created_after", "created_at", "created_after"),
        ]
    )
    def test_watermark_becomes_server_side_filter(self, _name: str, incremental_field: str | None, param: str) -> None:
        url = _issues_url("o1", extra=f"&{param}=2026-01-01T00%3A00%3A00Z")
        pages = {url: ([{"id": "i1"}], None)}
        with pytest.MonkeyPatch.context() as mp:
            rows = _collect(
                "issues",
                pages,
                _FakeResumableManager(),
                mp,
                organization_id="o1",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field=incremental_field,
            )
        assert rows == [{"id": "i1", "organization_id": "o1"}]

    def test_first_sync_has_no_filter(self, monkeypatch: Any) -> None:
        pages = {_issues_url("o1"): ([{"id": "i1"}], None)}
        rows = _collect(
            "issues",
            pages,
            _FakeResumableManager(),
            monkeypatch,
            organization_id="o1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert rows == [{"id": "i1", "organization_id": "o1"}]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        session = _FakeSession([_make_response(status_code, body={})])
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(snyk, "make_tracked_session", lambda *args, **kwargs: session)
            ok, _error = validate_credentials("us", "tok")
        assert ok is expected_ok
        # The probe must carry the mandatory dated version param or Snyk rejects the call.
        assert session.requested_urls == [f"{HOST}/rest/self?version={SNYK_REST_VERSION}"]

    def test_configured_org_is_probed_on_the_selected_region(self) -> None:
        session = _FakeSession([_make_response(200, body={})])
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(snyk, "make_tracked_session", lambda *args, **kwargs: session)
            ok, _error = validate_credentials("eu", "tok", "org-uuid-1")
        assert ok is True
        assert session.requested_urls == [f"https://api.eu.snyk.io/rest/orgs/org-uuid-1?version={SNYK_REST_VERSION}"]

    def test_invalid_org_id_fails_without_a_request(self) -> None:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(snyk, "make_tracked_session", lambda *args, **kwargs: _FakeSession([]))
            ok, error = validate_credentials("us", "tok", "../../self")
        assert ok is False
        assert error is not None

    def test_request_exception_is_failure(self) -> None:
        class _BoomSession:
            def get(self, *args: Any, **kwargs: Any) -> requests.Response:
                raise requests.exceptions.ConnectionError("boom")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(snyk, "make_tracked_session", lambda *args, **kwargs: _BoomSession())
            ok, error = validate_credentials("us", "tok")
        assert ok is False
        assert error is not None


class TestTokenRedaction:
    """The token rides in a custom `Authorization: token …` scheme the tracked transport's
    scrubber doesn't recognise, so every session it builds must redact the token by value."""

    def test_validate_credentials_redacts_token(self) -> None:
        captured: dict[str, Any] = {}

        def fake_make_session(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return _FakeSession([_make_response(200, body={})])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(snyk, "make_tracked_session", fake_make_session)
            validate_credentials("us", "super-secret-token")
        assert captured.get("redact_values") == ("super-secret-token",)

    def test_get_rows_redacts_token(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_make_session(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(snyk, "make_tracked_session", fake_make_session)
        monkeypatch.setattr(snyk, "_fetch_list_page", lambda *args, **kwargs: ([], None))
        list(
            get_rows(
                region="us",
                api_token="super-secret-token",
                organization_id=None,
                endpoint="organizations",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        assert captured.get("redact_values") == ("super-secret-token",)
