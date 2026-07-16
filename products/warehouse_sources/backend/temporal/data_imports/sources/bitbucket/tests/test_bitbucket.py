from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket import bitbucket
from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.bitbucket import (
    BitbucketAuth,
    BitbucketResumeConfig,
    _as_utc_datetime,
    _build_initial_params,
    _increment_page_url,
    _page_predates_cutoff,
    bitbucket_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.settings import BITBUCKET_ENDPOINTS

CUTOFF = datetime(2024, 6, 1, tzinfo=UTC)

REPO_PAGE = {
    "values": [
        {"slug": "repo-a", "uuid": "{uuid-a}", "full_name": "ws/repo-a"},
        {"slug": "repo-b", "uuid": "{uuid-b}", "full_name": "ws/repo-b"},
    ],
}


def _response(json_body: dict[str, Any], status: int = 200) -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status
    response.ok = status < 400
    response.text = ""
    response.json.return_value = json_body
    if status >= 400:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status} Client Error for url", response=response
        )
    return response


def _session_returning(*responses: mock.Mock) -> mock.Mock:
    session = mock.Mock()
    session.get.side_effect = list(responses)
    return session


def _manager(resume_state: BitbucketResumeConfig | None = None) -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _requested_urls(session: mock.Mock) -> list[str]:
    return [call.args[0] for call in session.get.call_args_list]


@pytest.mark.parametrize(
    "endpoint,should_use_incremental,cutoff,incremental_field,expected_q,expected_sort",
    [
        # Server-side BBQL filter + ascending sort on the chosen cursor field
        ("repositories", True, CUTOFF, "updated_on", 'updated_on > "2024-06-01T00:00:00+00:00"', "updated_on"),
        ("repositories", True, CUTOFF, "created_on", 'created_on > "2024-06-01T00:00:00+00:00"', "created_on"),
        ("pull_requests", True, CUTOFF, "updated_on", 'updated_on > "2024-06-01T00:00:00+00:00"', "updated_on"),
        # Full walk of a BBQL-capable endpoint sorts on immutable created_on for stable pages
        ("repositories", False, None, None, None, "created_on"),
        ("pull_requests", True, None, "updated_on", None, "created_on"),
        # Pipelines ignore `q`: newest-first sort only, watermark handled client-side
        ("pipelines", True, CUTOFF, "created_on", None, "-created_on"),
        # Commits have neither filter nor sort
        ("commits", True, CUTOFF, "date", None, None),
    ],
)
def test_build_initial_params_incremental_behavior(
    endpoint, should_use_incremental, cutoff, incremental_field, expected_q, expected_sort
):
    params = dict(
        _build_initial_params(BITBUCKET_ENDPOINTS[endpoint], should_use_incremental, cutoff, incremental_field)
    )
    assert params.get("q") == expected_q
    assert params.get("sort") == expected_sort


def test_build_initial_params_pull_requests_keeps_all_state_params():
    # The API defaults to OPEN-only; dropping the state params silently loses merged/declined PRs
    params = _build_initial_params(BITBUCKET_ENDPOINTS["pull_requests"], False, None, None)
    states = [value for key, value in params if key == "state"]
    assert states == ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"]
    assert ("pagelen", "50") in params  # PR list rejects pagelen > 50


@pytest.mark.parametrize(
    "items,expected",
    [
        ([{"date": "2024-01-01T00:00:00+00:00"}, {"date": "2023-12-01T00:00:00+00:00"}], True),
        # One row past the cutoff keeps paginating
        ([{"date": "2024-01-01T00:00:00+00:00"}, {"date": "2024-07-01T00:00:00+00:00"}], False),
        # Rows equal to the cutoff are already synced
        ([{"date": "2024-06-01T00:00:00+00:00"}], True),
        # Missing or unparseable timestamps must not truncate the walk
        ([{"date": None}], False),
        ([{}], False),
        ([], False),
        # Bitbucket pipelines emit nanosecond fractions
        ([{"date": "2024-05-21T01:50:36.611482242Z"}], True),
    ],
)
def test_page_predates_cutoff(items, expected):
    assert _page_predates_cutoff(items, "date", CUTOFF) is expected


def test_increment_page_url_preserves_sort_and_replaces_page():
    # Pipelines' `next` URL drops `sort`, silently reverting page 2+ to oldest-first;
    # rebuilding the URL ourselves must keep every param and bump only `page`.
    url = "https://api.bitbucket.org/2.0/repositories/ws/repo/pipelines/?pagelen=100&sort=-created_on&page=3"
    result = _increment_page_url(url, 3)
    query = dict(parse_qsl(urlsplit(result).query))
    assert query == {"pagelen": "100", "sort": "-created_on", "page": "4"}


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2024-05-21T01:50:36.611482242Z", datetime(2024, 5, 21, 1, 50, 36, 611482, tzinfo=UTC)),
        (datetime(2024, 5, 21), datetime(2024, 5, 21, tzinfo=UTC)),
        ("not a date", None),
        (None, None),
    ],
)
def test_as_utc_datetime(value, expected):
    assert _as_utc_datetime(value) == expected


def test_top_level_rows_follow_next_and_save_state_after_yield():
    manager = _manager()
    page_1 = {"values": [{"uuid": "{r1}"}], "next": "https://api.bitbucket.org/page2"}
    page_2 = {"values": [{"uuid": "{r2}"}]}
    session = _session_returning(_response(page_1), _response(page_2))

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        batches = list(get_rows(BitbucketAuth(), "ws", "repositories", mock.Mock(), manager))

    assert [[row["uuid"] for row in batch] for batch in batches] == [["{r1}"], ["{r2}"]]
    assert _requested_urls(session)[1] == "https://api.bitbucket.org/page2"
    # State saved only while more pages remain, so a crash re-yields (not skips) the last page
    manager.save_state.assert_called_once_with(BitbucketResumeConfig(next_url="https://api.bitbucket.org/page2"))


@pytest.mark.parametrize(
    "poisoned_url",
    [
        "https://evil.example.com/2.0/repositories/ws",
        "http://api.bitbucket.org/2.0/repositories/ws",  # https only
    ],
)
def test_fetch_page_rejects_off_origin_urls_without_sending_credentials(poisoned_url):
    # `next` URLs come from response bodies and resume state; following one off-origin
    # would hand the credentialed session to an arbitrary host
    session = mock.Mock()

    with pytest.raises(ValueError, match="Refusing to fetch non-Bitbucket URL"):
        bitbucket._fetch_page(session, poisoned_url, mock.Mock())

    session.get.assert_not_called()


def test_poisoned_resume_state_is_not_fetched():
    manager = _manager(BitbucketResumeConfig(next_url="https://evil.example.com/steal-token"))
    session = mock.Mock()

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        with pytest.raises(ValueError, match="Refusing to fetch non-Bitbucket URL"):
            list(get_rows(BitbucketAuth(), "ws", "repositories", mock.Mock(), manager))

    session.get.assert_not_called()


def test_top_level_rows_resume_from_saved_url():
    manager = _manager(BitbucketResumeConfig(next_url="https://api.bitbucket.org/resume-page"))
    session = _session_returning(_response({"values": [{"uuid": "{r3}"}]}))

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        batches = list(get_rows(BitbucketAuth(), "ws", "repositories", mock.Mock(), manager))

    assert _requested_urls(session) == ["https://api.bitbucket.org/resume-page"]
    assert batches == [[{"uuid": "{r3}"}]]


def test_workspace_members_rows_get_user_uuid_injected():
    member = {"type": "workspace_membership", "user": {"uuid": "{u1}", "display_name": "Jane"}}
    session = _session_returning(_response({"values": [member]}))

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        batches = list(get_rows(BitbucketAuth(), "ws", "workspace_members", mock.Mock(), _manager()))

    row = batches[0][0]
    assert row["user_uuid"] == "{u1}"
    assert row["user_display_name"] == "Jane"


def test_fan_out_injects_repository_context_and_advances_bookmark():
    manager = _manager()
    session = _session_returning(
        _response(REPO_PAGE),  # repo enumeration
        _response({"values": [{"id": 1}]}),  # repo-a pull requests
        _response({"values": [{"id": 1}]}),  # repo-b pull requests
    )

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        batches = list(get_rows(BitbucketAuth(), "ws", "pull_requests", mock.Mock(), manager))

    assert [batch[0]["repository_uuid"] for batch in batches] == ["{uuid-a}", "{uuid-b}"]
    assert batches[0][0]["repository_slug"] == "repo-a"
    assert batches[0][0]["repository_full_name"] == "ws/repo-a"
    urls = _requested_urls(session)
    assert "/repositories/ws/repo-a/pullrequests" in urls[1]
    assert "/repositories/ws/repo-b/pullrequests" in urls[2]
    # Bookmark advanced to repo-b after finishing repo-a, so a crash resumes there
    manager.save_state.assert_called_once_with(BitbucketResumeConfig(next_url=None, repo_slug="repo-b"))


def test_fan_out_resumes_from_bookmarked_repo():
    manager = _manager(BitbucketResumeConfig(next_url="https://api.bitbucket.org/repo-b-page3", repo_slug="repo-b"))
    session = _session_returning(
        _response(REPO_PAGE),
        _response({"values": [{"id": 7}]}),  # resumed page of repo-b
    )

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        batches = list(get_rows(BitbucketAuth(), "ws", "pull_requests", mock.Mock(), manager))

    # repo-a is skipped entirely; the walk restarts at repo-b's saved URL
    assert _requested_urls(session)[1] == "https://api.bitbucket.org/repo-b-page3"
    assert [batch[0]["repository_uuid"] for batch in batches] == ["{uuid-b}"]


def test_fan_out_skips_repo_on_404_and_continues():
    # Pipelines 404 on repos with Pipelines disabled; that must not fail the whole sync
    session = _session_returning(
        _response(REPO_PAGE),
        _response({}, status=404),  # repo-a pipelines disabled
        _response({"values": [{"uuid": "{p1}", "created_on": "2024-07-01T00:00:00Z"}]}),  # repo-b
    )

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        batches = list(get_rows(BitbucketAuth(), "ws", "pipelines", mock.Mock(), _manager()))

    assert [batch[0]["uuid"] for batch in batches] == ["{p1}"]


def test_fan_out_non_404_http_error_propagates():
    session = _session_returning(_response(REPO_PAGE), _response({}, status=403))

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        with pytest.raises(requests.exceptions.HTTPError):
            list(get_rows(BitbucketAuth(), "ws", "pipelines", mock.Mock(), _manager()))


def test_commits_incremental_stops_at_watermark_without_yielding_old_page():
    # Newest-first scroll: page 1 straddles the watermark (yielded), page 2 is entirely
    # older (not yielded, pagination stops without fetching page 3)
    page_1 = {
        "values": [{"hash": "new", "date": "2024-07-01T00:00:00+00:00"}],
        "next": "https://api.bitbucket.org/commits-page2",
    }
    page_2 = {
        "values": [{"hash": "old", "date": "2024-01-01T00:00:00+00:00"}],
        "next": "https://api.bitbucket.org/commits-page3",
    }
    session = _session_returning(
        _response({"values": [REPO_PAGE["values"][0]]}),
        _response(page_1),
        _response(page_2),
    )

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        batches = list(
            get_rows(
                BitbucketAuth(),
                "ws",
                "commits",
                mock.Mock(),
                _manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=CUTOFF,
                incremental_field="date",
            )
        )

    assert [[row["hash"] for row in batch] for batch in batches] == [["new"]]
    assert len(_requested_urls(session)) == 3  # enumeration + 2 pages, page 3 never fetched


def test_commits_first_sync_walks_past_old_pages():
    # No watermark on the first sync: an all-old page must still be yielded
    page = {"values": [{"hash": "old", "date": "2020-01-01T00:00:00+00:00"}]}
    session = _session_returning(_response({"values": [REPO_PAGE["values"][0]]}), _response(page))

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        batches = list(
            get_rows(BitbucketAuth(), "ws", "commits", mock.Mock(), _manager(), should_use_incremental_field=True)
        )

    assert [[row["hash"] for row in batch] for batch in batches] == [["old"]]


def test_pipelines_pagination_rebuilds_page_url_instead_of_following_next():
    # Following pipelines' `next` verbatim would drop `sort` and revert to oldest-first
    page_1 = {
        "values": [{"uuid": "{p1}", "created_on": "2024-07-02T00:00:00Z"}],
        "next": "https://api.bitbucket.org/2.0/repositories/ws/repo-a/pipelines/?page=2&pagelen=100",
        "page": 1,
    }
    page_2 = {"values": [{"uuid": "{p2}", "created_on": "2024-07-01T00:00:00Z"}], "page": 2}
    session = _session_returning(_response({"values": [REPO_PAGE["values"][0]]}), _response(page_1), _response(page_2))

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        batches = list(get_rows(BitbucketAuth(), "ws", "pipelines", mock.Mock(), _manager()))

    page_2_query = dict(parse_qsl(urlsplit(_requested_urls(session)[2]).query))
    assert page_2_query["sort"] == "-created_on"
    assert page_2_query["page"] == "2"
    assert [batch[0]["uuid"] for batch in batches] == ["{p1}", "{p2}"]


@pytest.mark.parametrize(
    "status,expected_valid,expected_message_fragment",
    [
        (200, True, None),
        (401, False, "Invalid Bitbucket credentials"),
        (403, False, "repository read access"),
        (404, False, "not found or not accessible"),
        (500, False, "500"),
    ],
)
def test_validate_credentials_status_mapping(status, expected_valid, expected_message_fragment):
    session = _session_returning(_response({}, status=status))

    with mock.patch.object(bitbucket, "_make_session", return_value=session):
        valid, message = validate_credentials(BitbucketAuth(email="a@b.c", api_token="t"), "ws")

    assert valid is expected_valid
    if expected_message_fragment is None:
        assert message is None
    else:
        assert expected_message_fragment in (message or "")


@pytest.mark.parametrize(
    "endpoint,expected_primary_keys,expected_sort_mode,expected_partition_key",
    [
        ("repositories", ["uuid"], "asc", "created_on"),
        # PR ids and commit hashes are only unique within a repo; a non-composite key
        # would seed duplicate rows and degrade every later merge
        ("pull_requests", ["repository_uuid", "id"], "desc", "created_on"),
        ("commits", ["repository_uuid", "hash"], "desc", "date"),
        ("pipelines", ["uuid"], "desc", "created_on"),
        ("deployments", ["uuid"], "desc", None),
        ("workspace_members", ["user_uuid"], "asc", None),
    ],
)
def test_source_response_shape(endpoint, expected_primary_keys, expected_sort_mode, expected_partition_key):
    response = bitbucket_source(BitbucketAuth(), "ws", endpoint, mock.Mock(), mock.Mock())
    assert response.name == endpoint
    assert response.primary_keys == expected_primary_keys
    assert response.sort_mode == expected_sort_mode
    if expected_partition_key is None:
        assert response.partition_keys is None
    else:
        assert response.partition_keys == [expected_partition_key]
        assert response.partition_mode == "datetime"


def test_session_uses_basic_auth_for_api_token_and_bearer_for_access_token():
    with mock.patch.object(bitbucket, "make_tracked_session", return_value=requests.Session()):
        basic = bitbucket._make_session(BitbucketAuth(email="a@b.c", api_token="tok"))
        assert basic.auth == ("a@b.c", "tok")
        assert "Authorization" not in basic.headers

    with mock.patch.object(bitbucket, "make_tracked_session", return_value=requests.Session()):
        bearer = bitbucket._make_session(BitbucketAuth(access_token="at"))
        assert bearer.headers["Authorization"] == "Bearer at"
        assert bearer.auth is None
