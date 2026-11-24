from datetime import UTC, datetime

import pytest
import time_machine

import jwt

from products.warehouse_sources.sources.ghost._config import GhostSourceConfig
from products.warehouse_sources.sources.ghost.ghost import GhostResumeConfig
from products.warehouse_sources.sources.ghost.source import GhostSource
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    error_message_matches,
)

KEY_ID = "0123456789abcdef01234567"
KEY_SECRET = "0123456789abcdef" * 4
API_KEY = f"{KEY_ID}:{KEY_SECRET}"


def driver(admin_domain: str = "publication.example.com") -> SourceDriver:
    return SourceDriver(GhostSource(), GhostSourceConfig(admin_domain=admin_domain, admin_api_key=API_KEY))


@pytest.mark.parametrize(
    ("endpoint", "include", "formats"),
    [
        ("members", "tiers", None),
        ("posts", "tags,authors,email,newsletter", "html,lexical"),
        ("pages", "tags,authors", "html,lexical"),
        ("tiers", "monthly_price,yearly_price,benefits", None),
        ("newsletters", None, None),
        ("tags", None, None),
        ("users", None, None),
        ("labels", "count.members", None),
    ],
)
def test_browse_requests_preserve_rows_and_stop_at_last_page(
    endpoint: str, include: str | None, formats: str | None
) -> None:
    rows = [
        {"id": "first", "created_at": "2026-01-01T00:00:00.000Z", "subscriptions": [], "email_open_rate": None},
        {
            "id": "second",
            "created_at": "2026-01-02T00:00:00.000Z",
            "subscriptions": [{"customer": {"id": "cus_example"}}],
        },
    ]
    result = driver("https://publication.example.com/blog/ghost/api/admin/").run(
        endpoint,
        [
            ScriptedResponse(json={endpoint: [rows[0]], "meta": {"pagination": {"page": 1, "pages": 2, "next": 2}}}),
            ScriptedResponse(json={endpoint: [rows[1]], "meta": {"pagination": {"page": 2, "pages": 2, "next": None}}}),
        ],
        should_use_incremental_field=True,
        db_incremental_field_last_value="2099-01-01T00:00:00Z",
    )
    assert result.raised is None
    assert result.rows == rows
    assert result.paths == [f"/blog/ghost/api/admin/{endpoint}/"] * 2
    assert result.params("page") == ["1", "2"]
    assert result.params("include") == [include, include]
    assert result.params("formats") == [formats, formats]
    assert result.params("filter") == [None, None]
    assert result.params("order") == ["created_at asc,id asc"] * 2
    assert result.committed_states == [GhostResumeConfig(page=2), GhostResumeConfig(finished=True)]
    assert all(request.headers["accept-version"] == "v6.0" for request in result.requests)


@pytest.mark.parametrize(
    ("endpoint", "path", "data_selector", "status_filter", "rows"),
    [
        (
            "offers",
            "/ghost/api/admin/offers/",
            "offers",
            None,
            [{"id": "offer_example", "tier": {"id": "tier_example"}, "redemption_count": 0}],
        ),
        (
            "member_custom_fields",
            "/ghost/api/admin/members/metafields/custom/",
            "members_metafields",
            "status:[active,archived]",
            [
                {"namespace": "custom", "key": "team_size", "type": "short_text", "status": "active"},
                {
                    "namespace": "custom",
                    "key": "favorite_topics",
                    "type": "list",
                    "settings": {"options": ["Alpha", "Beta"], "multiple": True},
                    "status": "archived",
                    "updated_at": None,
                },
            ],
        ),
        (
            "roles",
            "/ghost/api/admin/roles/",
            "roles",
            None,
            [{"id": "role_example", "name": "Example role", "created_at": "2026-01-01T00:00:00.000Z"}],
        ),
    ],
)
def test_unpaginated_endpoints_read_one_response_without_repeating_it(
    endpoint: str, path: str, data_selector: str, status_filter: str | None, rows: list[dict]
) -> None:
    result = driver().run(endpoint, [ScriptedResponse(json={data_selector: rows})])
    assert result.raised is None
    assert result.rows == rows
    assert result.paths == [path]
    assert result.params("page") == [None]
    assert result.params("limit") == [None]
    assert result.params("filter") == [status_filter]
    assert result.committed_states == [GhostResumeConfig(finished=True)]


@pytest.mark.parametrize(
    ("endpoint", "non_retryable"),
    [("member_custom_fields", True), ("roles", False)],
)
def test_missing_route_on_an_older_site_fails_without_retries_only_for_custom_fields(
    endpoint: str, non_retryable: bool
) -> None:
    result = driver().run(endpoint, [ScriptedResponse(status=404, json={"errors": [{"type": "NotFoundError"}]})])
    assert result.raised is not None
    assert result.rows == []
    assert error_message_matches(str(result.raised), GhostSource().get_non_retryable_errors()) is non_retryable


def test_resume_keeps_written_pages_and_does_not_replay_a_finished_run() -> None:
    first = driver().run(
        "members",
        [
            ScriptedResponse(json={"members": [{"id": "first"}], "meta": {"pagination": {"pages": 2}}}),
            ScriptedResponse(json={"unexpected": []}),
        ],
    )
    assert first.raised is not None
    assert first.rows == [{"id": "first"}]
    assert first.committed_states == [GhostResumeConfig(page=2)]
    resumed = driver().run(
        "members",
        [ScriptedResponse(json={"members": [{"id": "second"}], "meta": {"pagination": {"pages": 2}}})],
        resume_state=first.committed_states[-1],
    )
    assert resumed.raised is None
    assert resumed.params("page") == ["2"]
    assert resumed.rows == [{"id": "second"}]
    finished = driver().run("members", [], resume_state=resumed.committed_states[-1])
    assert finished.raised is None
    assert finished.rows == []
    assert finished.requests == []


def test_requests_mint_a_new_signed_token_after_five_minutes() -> None:
    issued_at: list[int] = []
    with time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False) as clock:

        def respond(request: RecordedRequest) -> ScriptedResponse:
            scheme, token = request.headers["authorization"].split(" ", 1)
            assert scheme == "Ghost"
            payload = jwt.decode(token, bytes.fromhex(KEY_SECRET), algorithms=["HS256"], audience="/admin/")
            assert jwt.get_unverified_header(token)["kid"] == KEY_ID
            assert payload["exp"] - payload["iat"] == 300
            issued_at.append(payload["iat"])
            clock.shift(360)
            return ScriptedResponse(
                json={"members": [{"id": request.param("page")}], "meta": {"pagination": {"pages": 2}}}
            )

        result = driver().run("members", respond)
    assert result.raised is None
    assert issued_at[1] - issued_at[0] == 360
    assert API_KEY in result.session_options[0]["redact_values"]
    assert KEY_SECRET in result.session_options[0]["redact_values"]
