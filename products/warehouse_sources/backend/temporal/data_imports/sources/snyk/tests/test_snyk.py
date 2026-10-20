from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.snyk import SnykSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.snyk import (
    SNYK_REST_VERSION,
    SnykResumeConfig,
    _next_page_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.source import SnykSource

HOST = "https://api.snyk.io"


def _list_body(items: list[dict], next_link: Any = None) -> dict:
    body: dict[str, Any] = {"data": items}
    if next_link is not None:
        body["links"] = {"next": next_link}
    return body


def _page(items: list[dict], next_link: Any = None) -> ScriptedResponse:
    return ScriptedResponse(json=_list_body(items, next_link))


def _run(
    endpoint: str,
    script: Script,
    *,
    resume_state: SnykResumeConfig | None = None,
    api_token: str = "tok",
    organization_id: str | None = None,
    **inputs: Any,
) -> DriveResult:
    config = SnykSourceConfig(api_token=api_token, region="us", organization_id=organization_id)
    return SourceDriver(SnykSource(), config).run(endpoint, script, resume_state=resume_state, **inputs)


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


class TestRetryClassification:
    def test_client_error_raises_without_retry(self) -> None:
        # 401 is a permanent auth failure — surfaced immediately as an HTTPError, no retry.
        result = _run("organizations", [ScriptedResponse(status=401, json={"errors": [{"status": "401"}]})])
        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1


class TestTopLevelOrganizations:
    def test_saves_state_after_yield_and_resumes_from_it(self) -> None:
        page2 = f"{HOST}/rest/orgs?version={SNYK_REST_VERSION}&limit=100&starting_after=cursor"
        result = _run("organizations", [_page([{"id": "o1"}], next_link=page2), _page([{"id": "o2"}])])
        # Checkpoint saved after the first (full) page, pointing at the next-page URL.
        assert any(s.next_url == page2 for s in result.saved_states)

        # A resumed run seeds the request from the saved next URL.
        resumed = _run("organizations", [_page([{"id": "o2"}])], resume_state=SnykResumeConfig(next_url=page2))
        assert resumed.rows == [{"id": "o2"}]
        assert resumed.urls[0] == page2

    def test_resume_state_on_wrong_host_is_rejected(self) -> None:
        # The resume URL is fetched with the auth header attached, so tampered state must not be
        # able to redirect the request off the Snyk host.
        result = _run("organizations", [], resume_state=SnykResumeConfig(next_url="https://evil.example.com/rest/orgs"))
        assert isinstance(result.raised, ValueError)
        assert result.requests == []

    def test_configured_org_fetches_single_org_directly(self) -> None:
        # A single-org connection must not enumerate every org: it fetches /orgs/{org_id} directly
        # and emits only that org.
        result = _run(
            "organizations",
            [ScriptedResponse(json={"data": {"id": "o9", "type": "org", "attributes": {"name": "Org 9"}}})],
            organization_id="o9",
        )
        assert result.rows == [{"id": "o9", "type": "org", "name": "Org 9"}]
        assert result.urls == [f"{HOST}/rest/orgs/o9?version={SNYK_REST_VERSION}"]

    def test_configured_org_id_is_validated_before_the_request(self) -> None:
        # The org id is interpolated into the URL path, so a path-altering value must be rejected
        # up front — before any resource is built or request made.
        result = _run("organizations", [], organization_id="../self")
        assert isinstance(result.raised, ValueError)
        assert result.requests == []


class TestPerOrgFanOut:
    def test_walks_every_org_and_injects_organization_id(self) -> None:
        result = _run(
            "issues",
            [
                _page([{"id": "o1"}, {"id": "o2"}]),
                _page([{"id": "i1", "attributes": {"title": "a"}}]),
                _page([{"id": "i2", "attributes": {"title": "b"}}]),
            ],
        )
        assert result.rows == [
            {"id": "i1", "title": "a", "organization_id": "o1"},
            {"id": "i2", "title": "b", "organization_id": "o2"},
        ]

    def test_invalid_configured_org_id_is_rejected(self) -> None:
        result = _run("issues", [], organization_id="../self")
        assert isinstance(result.raised, ValueError)
        assert result.requests == []


class TestIncrementalFilters:
    @parameterized.expand(
        [
            ("default_field", None, "updated_after"),
            ("explicit_updated_at", "updated_at", "updated_after"),
            ("created_at_maps_to_created_after", "created_at", "created_after"),
        ]
    )
    def test_watermark_becomes_server_side_filter(self, _name: str, incremental_field: str | None, param: str) -> None:
        result = _run(
            "issues",
            [_page([{"id": "i1"}])],
            organization_id="o1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field=incremental_field,
        )
        assert result.rows == [{"id": "i1", "organization_id": "o1"}]
        assert result.requests[0].param(param) == "2026-01-01T00:00:00Z"

    def test_first_sync_has_no_filter(self) -> None:
        result = _run(
            "issues",
            [_page([{"id": "i1"}])],
            organization_id="o1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert result.rows == [{"id": "i1", "organization_id": "o1"}]
        assert result.requests[0].param("updated_after") is None
        assert result.requests[0].param("created_after") is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            ok, _error = validate_credentials("us", "tok")
        assert ok is expected_ok
        # The probe must carry the mandatory dated version param or Snyk rejects the call.
        assert network.requests_log[0].url == f"{HOST}/rest/self?version={SNYK_REST_VERSION}"

    def test_configured_org_is_probed_on_the_selected_region(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            ok, _error = validate_credentials("eu", "tok", "org-uuid-1")
        assert ok is True
        assert network.requests_log[0].url == f"https://api.eu.snyk.io/rest/orgs/org-uuid-1?version={SNYK_REST_VERSION}"

    def test_invalid_org_id_fails_without_a_request(self) -> None:
        with scripted_network([]) as network:
            ok, error = validate_credentials("us", "tok", "../../self")
        assert ok is False
        assert error is not None
        assert network.requests_log == []


class TestTokenRedaction:
    """The token rides in a custom `Authorization: token …` scheme; every tracked session built for
    Snyk must redact it by value so it can't leak into logs or error messages."""

    def test_validate_credentials_redacts_token(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("us", "super-secret-token")
        assert network.session_options[0].get("redact_values") == ("super-secret-token",)

    def test_source_redacts_token(self) -> None:
        result = _run("organizations", [_page([{"id": "o1"}])], api_token="super-secret-token")
        # The framework derives the redaction set from the auth's secret values; the token is
        # carried inside the `token <token>` api-key value.
        redact_values = [value for options in result.session_options for value in options.get("redact_values") or ()]
        assert any("super-secret-token" in value for value in redact_values)
