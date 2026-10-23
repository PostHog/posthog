import dataclasses
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket import bitbucket
from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.bitbucket import (
    BitbucketAuth,
    BitbucketResumeConfig,
    _build_initial_params,
    _iter_fan_out_parents,
    _page_predates_cutoff,
    _parent_precedes_bookmark,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.settings import BITBUCKET_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bitbucket.source import BitbucketSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bitbucket import (
    BitbucketAuthMethodConfig,
    BitbucketSourceConfig,
)

CUTOFF = datetime(2024, 6, 1, tzinfo=UTC)

REPO_PAGE = {
    "values": [
        {"slug": "repo-a", "uuid": "{uuid-a}", "full_name": "ws/repo-a"},
        {"slug": "repo-b", "uuid": "{uuid-b}", "full_name": "ws/repo-b"},
    ],
}


def _driver() -> SourceDriver:
    return SourceDriver(
        BitbucketSource(),
        BitbucketSourceConfig(
            workspace="ws",
            auth_method=BitbucketAuthMethodConfig(email="a@b.c", api_token="tok"),
        ),
    )


def _page(json_body: dict[str, Any], status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=json_body)


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
        # Projects filter and sort server-side, like repositories
        ("projects", True, CUTOFF, "updated_on", 'updated_on > "2024-06-01T00:00:00+00:00"', "updated_on"),
        # PR comments filter server-side on the child request
        ("pull_request_comments", True, CUTOFF, "updated_on", 'updated_on > "2024-06-01T00:00:00+00:00"', "updated_on"),
        # The step and status child requests take no filter of their own; the watermark bounds
        # their parent walk instead
        ("pipeline_steps", True, CUTOFF, "pipeline_created_on", None, None),
        ("commit_statuses", True, CUTOFF, "commit_date", None, None),
        # Branches are full refresh, but still sort explicitly so pages can't shift mid-walk
        ("branches", False, None, None, None, "name"),
        # The activity feed ignores both, so neither param is sent
        ("pull_request_activity", True, CUTOFF, "activity_date", None, None),
        # Environments have no cursor at all
        ("environments", False, None, None, None, None),
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


def test_top_level_rows_follow_next_and_save_state_after_yield():
    page_1 = {"values": [{"uuid": "{r1}"}], "next": "https://api.bitbucket.org/page2"}
    page_2 = {"values": [{"uuid": "{r2}"}]}
    result = _driver().run("repositories", [_page(page_1), _page(page_2)])

    assert result.raised is None
    assert [[row["uuid"] for row in batch] for batch in result.items] == [["{r1}"], ["{r2}"]]
    assert result.urls[1] == "https://api.bitbucket.org/page2"
    # State saved only while more pages remain, so a crash re-yields (not skips) the last page
    assert result.saved_states == [BitbucketResumeConfig(next_url="https://api.bitbucket.org/page2")]
    assert result.committed_states == [BitbucketResumeConfig(next_url="https://api.bitbucket.org/page2")]
    assert result.final_state == BitbucketResumeConfig(next_url="https://api.bitbucket.org/page2")


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
    session = Mock()

    with pytest.raises(ValueError, match="Refusing to fetch non-Bitbucket URL"):
        bitbucket._fetch_page(session, poisoned_url, Mock())

    session.get.assert_not_called()


def test_fetch_page_exhausted_5xx_is_classified_retryable(monkeypatch):
    # The raised message and BitbucketSource.get_retryable_errors are two halves of one contract:
    # a rewording on either side sends a Bitbucket outage to error tracking as a PostHog exception.
    monkeypatch.setattr(cast(Any, bitbucket._fetch_page).retry, "wait", lambda _: 0)
    session = Mock()
    session.get.return_value = Mock(status_code=503)

    with pytest.raises(bitbucket.BitbucketRetryableError) as raised:
        bitbucket._fetch_page(session, "https://api.bitbucket.org/2.0/repositories/ws", Mock())

    assert error_message_matches(str(raised.value), BitbucketSource().get_retryable_errors())
    assert not error_message_matches(str(raised.value), BitbucketSource().get_non_retryable_errors().keys())


def test_fetch_page_exhausted_read_timeout_is_classified_retryable(monkeypatch):
    # Same contract as the 5xx case above, for a read timeout that outlasts every try.
    monkeypatch.setattr(cast(Any, bitbucket._fetch_page).retry, "wait", lambda _: 0)
    session = Mock()
    session.get.side_effect = requests.ReadTimeout(
        "HTTPSConnectionPool(host='api.bitbucket.org', port=443): Read timed out. (read timeout=37.0)"
    )

    with pytest.raises(requests.ReadTimeout) as raised:
        bitbucket._fetch_page(session, "https://api.bitbucket.org/2.0/repositories/ws", Mock())

    assert error_message_matches(str(raised.value), BitbucketSource().get_retryable_errors())
    assert not error_message_matches(str(raised.value), BitbucketSource().get_non_retryable_errors().keys())


def test_poisoned_resume_state_is_not_fetched():
    result = _driver().run(
        "repositories",
        [],
        resume_state=BitbucketResumeConfig(next_url="https://evil.example.com/steal-token"),
    )

    assert isinstance(result.raised, ValueError)
    assert "Refusing to fetch non-Bitbucket URL" in str(result.raised)
    assert result.requests == []
    assert result.final_state == BitbucketResumeConfig(next_url="https://evil.example.com/steal-token")


def test_workspace_members_rows_get_user_uuid_injected():
    member = {"type": "workspace_membership", "user": {"uuid": "{u1}", "display_name": "Jane"}}
    result = _driver().run("workspace_members", [_page({"values": [member]})])

    assert result.raised is None
    row = result.rows[0]
    assert row["user_uuid"] == "{u1}"
    assert row["user_display_name"] == "Jane"


def test_fan_out_injects_repository_context_and_advances_bookmark():
    result = _driver().run(
        "pull_requests",
        [
            _page(REPO_PAGE),  # repo enumeration
            _page({"values": [{"id": 1}]}),  # repo-a pull requests
            _page({"values": [{"id": 1}]}),  # repo-b pull requests
        ],
    )

    assert result.raised is None
    assert [batch[0]["repository_uuid"] for batch in result.items] == ["{uuid-a}", "{uuid-b}"]
    assert result.items[0][0]["repository_slug"] == "repo-a"
    assert result.items[0][0]["repository_full_name"] == "ws/repo-a"
    assert "/repositories/ws/repo-a/pullrequests" in result.paths[1]
    assert "/repositories/ws/repo-b/pullrequests" in result.paths[2]
    # Bookmark advanced to repo-b after finishing repo-a, so a crash resumes there
    assert result.saved_states == [BitbucketResumeConfig(next_url=None, repo_slug="repo-b")]


def test_fan_out_resumes_from_bookmarked_repo():
    result = _driver().run(
        "pull_requests",
        [
            _page(REPO_PAGE),
            _page({"values": [{"id": 7}]}),  # resumed page of repo-b
        ],
        resume_state=BitbucketResumeConfig(next_url="https://api.bitbucket.org/repo-b-page3", repo_slug="repo-b"),
    )

    assert result.raised is None
    # repo-a is skipped entirely; the walk restarts at repo-b's saved URL
    assert result.urls[1] == "https://api.bitbucket.org/repo-b-page3"
    assert [batch[0]["repository_uuid"] for batch in result.items] == ["{uuid-b}"]


def test_fan_out_skips_repo_on_404_and_continues():
    # Pipelines 404 on repos with Pipelines disabled; that must not fail the whole sync
    result = _driver().run(
        "pipelines",
        [
            _page(REPO_PAGE),
            _page({}, status=404),  # repo-a pipelines disabled
            _page({"values": [{"uuid": "{p1}", "created_on": "2024-07-01T00:00:00Z"}]}),  # repo-b
        ],
    )

    assert result.raised is None
    assert [row["uuid"] for row in result.rows] == ["{p1}"]


def test_fan_out_non_404_http_error_propagates():
    result = _driver().run("pipelines", [_page(REPO_PAGE), _page({}, status=403)])

    assert isinstance(result.raised, requests.exceptions.HTTPError)


def test_pipelines_pagination_rebuilds_page_url_instead_of_following_next():
    # Following pipelines' `next` verbatim would drop `sort` and revert to oldest-first
    page_1 = {
        "values": [{"uuid": "{p1}", "created_on": "2024-07-02T00:00:00Z"}],
        "next": "https://api.bitbucket.org/2.0/repositories/ws/repo-a/pipelines/?page=2&pagelen=100",
        "page": 1,
    }
    page_2 = {"values": [{"uuid": "{p2}", "created_on": "2024-07-01T00:00:00Z"}], "page": 2}
    result = _driver().run("pipelines", [_page({"values": [REPO_PAGE["values"][0]]}), _page(page_1), _page(page_2)])

    assert result.raised is None
    assert result.requests[2].param("sort") == "-created_on"
    assert result.requests[2].param("page") == "2"
    assert [row["uuid"] for row in result.rows] == ["{p1}", "{p2}"]


@pytest.mark.parametrize(
    "status,expected_valid,expected_message_fragment",
    [
        (404, False, "not found or not accessible"),
    ],
)
def test_validate_credentials_status_mapping(status, expected_valid, expected_message_fragment):
    with scripted_network(always(_page({}, status=status))) as network:
        valid, message = validate_credentials(BitbucketAuth(email="a@b.c", api_token="t"), "ws")

    assert network.requests_log[0].path == "/2.0/repositories/ws"
    assert network.requests_log[0].param("pagelen") == "1"
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
        ("projects", ["uuid"], "asc", "created_on"),
        ("environments", ["uuid"], "desc", None),
        (
            "pull_request_activity",
            ["repository_uuid", "pull_request_id", "activity_type", "activity_date"],
            "desc",
            "activity_date",
        ),
        ("pull_request_comments", ["repository_uuid", "pull_request_id", "id"], "desc", "created_on"),
        ("pipeline_steps", ["repository_uuid", "pipeline_uuid", "uuid"], "desc", "pipeline_created_on"),
        ("commit_statuses", ["repository_uuid", "commit_hash", "key"], "desc", "commit_date"),
        ("branches", ["repository_uuid", "name"], "desc", None),
    ],
)
def test_source_response_shape(endpoint, expected_primary_keys, expected_sort_mode, expected_partition_key):
    result = _driver().run(endpoint, always(_page({"values": []})))
    assert result.raised is None
    response = result.response
    assert response is not None
    assert response.name == endpoint
    assert response.primary_keys == expected_primary_keys
    assert response.sort_mode == expected_sort_mode
    if expected_partition_key is None:
        assert response.partition_keys is None
    else:
        assert response.partition_keys == [expected_partition_key]
        assert response.partition_mode == "datetime"


def test_activity_incremental_stops_at_watermark_on_the_lifted_date():
    # The cutoff has to be applied after the rows are normalized, because the raw entries have no
    # top-level timestamp, so checking them would never stop the newest-first scroll
    fresh = {
        "values": [{"pull_request": {"id": 1}, "approval": {"date": "2024-07-01T00:00:00+00:00"}}],
        "next": "https://api.bitbucket.org/2.0/repositories/ws/repo-a/pullrequests/activity?ctx=p2",
    }
    stale = {
        "values": [{"pull_request": {"id": 2}, "approval": {"date": "2023-01-01T00:00:00+00:00"}}],
        "next": "https://api.bitbucket.org/2.0/repositories/ws/repo-a/pullrequests/activity?ctx=p3",
    }
    result = _driver().run(
        "pull_request_activity",
        [_page({"values": [REPO_PAGE["values"][0]]}), _page(fresh), _page(stale)],
        should_use_incremental_field=True,
        db_incremental_field_last_value=CUTOFF,
    )

    assert result.raised is None
    assert [[row["pull_request_id"] for row in batch] for batch in result.items] == [[1]]
    # The stale page was fetched to discover it was stale, but page 3 never was
    assert len(result.requests) == 3


def test_pull_request_fan_out_walks_every_pull_request_and_injects_context():
    result = _driver().run(
        "pull_request_comments",
        [
            _page({"values": [REPO_PAGE["values"][0]]}),  # repo enumeration
            _page({"values": [{"id": 11}, {"id": 12}]}),  # repo-a pull requests
            _page({"values": [{"id": 501, "pullrequest": {"id": 11}, "user": {"uuid": "{u1}"}}]}),
            _page({"values": [{"id": 502, "pullrequest": {"id": 12}, "user": {"uuid": "{u2}"}}]}),
        ],
    )

    assert result.raised is None
    assert "/repositories/ws/repo-a/pullrequests/11/comments" in result.paths[2]
    assert "/repositories/ws/repo-a/pullrequests/12/comments" in result.paths[3]
    assert [(row["id"], row["pull_request_id"], row["repository_uuid"], row["user_uuid"]) for row in result.rows] == [
        (501, 11, "{uuid-a}", "{u1}"),
        (502, 12, "{uuid-a}", "{u2}"),
    ]


@pytest.mark.parametrize(
    "should_use_incremental,last_value,expected_q",
    [
        # An unbounded parent walk would issue one request per pull request that ever
        # existed on every sync
        (True, CUTOFF, 'updated_on > "2024-06-01T00:00:00+00:00"'),
        (True, None, None),
        (False, CUTOFF, None),
    ],
)
def test_pull_request_fan_out_bounds_the_parent_walk(should_use_incremental, last_value, expected_q):
    result = _driver().run(
        "pull_request_comments",
        [_page({"values": [REPO_PAGE["values"][0]]}), _page({"values": []})],
        should_use_incremental_field=should_use_incremental,
        db_incremental_field_last_value=last_value,
    )

    assert result.raised is None
    assert result.requests[1].param("q") == expected_q
    # Sorted on the immutable created_on so ids arrive ascending for the resume bookmark
    assert result.requests[1].param("sort") == "created_on"


def test_pipeline_steps_drop_the_private_registry_password():
    # A step pulling from a private registry carries the registry password in `image`;
    # syncing it would hand the credential to anyone with warehouse query access
    result = _driver().run(
        "pipeline_steps",
        [
            _page({"values": [REPO_PAGE["values"][0]]}),
            _page({"values": [{"uuid": "{p1}", "created_on": "2024-07-01T00:00:00Z"}], "page": 1}),
            _page(
                {
                    "values": [
                        {"uuid": "{s1}", "image": {"name": "acme/build", "username": "ci", "password": "hunter2"}},
                        {"uuid": "{s2}", "image": {"name": "python:3.12"}},
                        {"uuid": "{s3}"},
                    ]
                }
            ),
        ],
    )

    assert result.raised is None
    assert [row.get("image") for row in result.rows] == [
        {"name": "acme/build", "username": "ci"},
        {"name": "python:3.12"},
        None,
    ]


def test_pull_request_fan_out_skips_a_deleted_pull_request_without_dropping_the_repo():
    result = _driver().run(
        "pull_request_comments",
        [
            _page(REPO_PAGE),
            _page({"values": [{"id": 11}, {"id": 12}]}),  # repo-a pull requests
            _page({}, status=404),  # PR 11 deleted between the listing and the fetch
            _page({"values": [{"id": 502, "pullrequest": {"id": 12}}]}),
            _page({"values": [{"id": 21}]}),  # repo-b pull requests
            _page({"values": [{"id": 601, "pullrequest": {"id": 21}}]}),
        ],
    )

    assert result.raised is None
    # PR 12 and repo-b still sync; only the deleted pull request is skipped
    assert [row["id"] for row in result.rows] == [502, 601]


def test_pull_request_fan_out_skips_repo_when_the_pull_request_listing_404s():
    result = _driver().run(
        "pull_request_comments",
        [
            _page(REPO_PAGE),
            _page({}, status=404),  # repo-a deleted between enumeration and the walk
            _page({"values": [{"id": 21}]}),  # repo-b pull requests
            _page({"values": [{"id": 601, "pullrequest": {"id": 21}}]}),
        ],
    )

    assert result.raised is None
    assert [row["id"] for row in result.rows] == [601]


@pytest.mark.parametrize(
    "order,value,bookmark,expected",
    [
        # Pull requests are walked oldest-first by id, so anything below the bookmark is done
        ("id_asc", 11, "12", True),
        ("id_asc", 12, "12", False),
        ("id_asc", 13, "12", False),
        # Pipelines and commits are walked newest-first, so anything newer is done
        ("datetime_desc", "2024-07-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00", True),
        ("datetime_desc", "2024-05-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00", False),
        # A parent we cannot place must be re-walked, never skipped
        ("id_asc", None, "12", False),
        ("datetime_desc", None, "2024-06-01T00:00:00+00:00", False),
        ("datetime_desc", "not a date", "2024-06-01T00:00:00+00:00", False),
    ],
)
def test_parent_precedes_bookmark(order, value, bookmark, expected):
    assert _parent_precedes_bookmark(order, value, bookmark) is expected


def test_fan_out_parent_walk_stops_at_the_cap_and_warns():
    # One request per parent, so an uncapped first sync of a long-lived repo would outlast
    # any rate budget. Truncating silently would be worse than the cost, hence the warning.
    pipeline_steps_fan_out = BITBUCKET_ENDPOINTS["pipeline_steps"].fan_out
    assert pipeline_steps_fan_out is not None
    fan_out = dataclasses.replace(pipeline_steps_fan_out, max_parents_per_repo=2)
    page = {
        "values": [{"uuid": "{p1}"}, {"uuid": "{p2}"}, {"uuid": "{p3}"}],
        "next": "https://api.bitbucket.org/2.0/repositories/ws/repo-a/pipelines/?page=2",
        "page": 1,
    }
    logger = MagicMock()

    with scripted_network([_page(page)]):
        parents = list(_iter_fan_out_parents(requests.Session(), fan_out, "ws", "repo-a", logger, None))

    assert [parent["uuid"] for parent in parents] == ["{p1}", "{p2}"]
    logger.warning.assert_called_once()


@pytest.mark.parametrize(
    "endpoint,parent,expected_path,expected_injected",
    [
        # Pipeline uuids are braced, which is not path-safe
        (
            "pipeline_steps",
            {"uuid": "{p1}", "created_on": "2024-07-01T00:00:00Z"},
            "/pipelines/%7Bp1%7D/steps/",
            {"pipeline_uuid": "{p1}", "pipeline_created_on": "2024-07-01T00:00:00Z"},
        ),
        (
            "commit_statuses",
            {"hash": "abc123", "date": "2024-07-01T00:00:00+00:00"},
            "/commit/abc123/statuses",
            {"commit_hash": "abc123", "commit_date": "2024-07-01T00:00:00+00:00"},
        ),
    ],
)
def test_second_level_fan_out_injects_the_parent_the_child_row_cannot_name(
    endpoint, parent, expected_path, expected_injected
):
    # Neither a step nor a status carries a reference back to its parent, and both the
    # primary key and the partition key read only the injected columns
    result = _driver().run(
        endpoint,
        [
            _page({"values": [REPO_PAGE["values"][0]]}),  # repo enumeration
            _page({"values": [parent], "page": 1}),
            _page({"values": [{"uuid": "{s1}", "key": "BB-DEPLOY"}]}),
        ],
    )

    assert result.raised is None
    assert expected_path in result.paths[2]
    row = result.rows[0]
    assert {column: row[column] for column in expected_injected} == expected_injected
    assert row["repository_uuid"] == "{uuid-a}"


def test_pipeline_steps_incremental_stops_the_pipeline_walk_at_the_watermark():
    # Pipelines ignore `q`, so the watermark has to stop the parent walk client-side. Without
    # it every sync would fetch the steps of every pipeline that ever ran.
    fresh = {
        "values": [{"uuid": "{p1}", "created_on": "2024-07-01T00:00:00Z"}],
        "next": "https://api.bitbucket.org/2.0/repositories/ws/repo-a/pipelines/?page=2",
        "page": 1,
    }
    stale = {"values": [{"uuid": "{p2}", "created_on": "2023-01-01T00:00:00Z"}], "page": 2}
    result = _driver().run(
        "pipeline_steps",
        [
            _page({"values": [REPO_PAGE["values"][0]]}),
            _page(fresh),
            _page({"values": [{"uuid": "{s1}"}]}),  # steps of {p1}
            _page(stale),
        ],
        should_use_incremental_field=True,
        db_incremental_field_last_value=CUTOFF,
        incremental_field="pipeline_created_on",
    )

    assert result.raised is None
    assert [row["pipeline_uuid"] for row in result.rows] == ["{p1}"]
    # The stale pipeline page was fetched to discover it was stale, but its steps never were
    assert len(result.requests) == 4


def test_second_level_fan_out_resumes_past_already_walked_parents():
    result = _driver().run(
        "pipeline_steps",
        [
            _page(REPO_PAGE),
            _page(
                {
                    "values": [
                        {"uuid": "{p1}", "created_on": "2024-07-03T00:00:00Z"},
                        {"uuid": "{p2}", "created_on": "2024-07-02T00:00:00Z"},
                        {"uuid": "{p3}", "created_on": "2024-07-01T00:00:00Z"},
                    ],
                    "page": 1,
                }
            ),
            _page({"values": [{"uuid": "{s2}"}]}),  # resumed page of {p2}
            _page({"values": [{"uuid": "{s3}"}]}),
        ],
        resume_state=BitbucketResumeConfig(
            next_url="https://api.bitbucket.org/2.0/steps-page-2",
            repo_slug="repo-b",
            parent_id="{p2}",
            parent_cursor="2024-07-02T00:00:00Z",
        ),
    )

    assert result.raised is None
    # repo-a is skipped, {p1} is newer than the bookmark, and {p2} restarts at its saved URL
    assert result.urls[1].startswith("https://api.bitbucket.org/2.0/repositories/ws/repo-b/pipelines/?")
    assert result.urls[2] == "https://api.bitbucket.org/2.0/steps-page-2"
    assert "/pipelines/%7Bp3%7D/steps/" in result.urls[3]
    assert [row["uuid"] for row in result.rows] == ["{s2}", "{s3}"]


def test_session_uses_basic_auth_for_api_token_and_bearer_for_access_token():
    with scripted_network([_page({"values": []})]) as basic_network:
        assert validate_credentials(BitbucketAuth(email="a@b.c", api_token="tok"), "ws") == (True, None)

    with scripted_network([_page({"values": []})]) as bearer_network:
        assert validate_credentials(BitbucketAuth(access_token="at"), "ws") == (True, None)

    assert basic_network.requests_log[0].headers["authorization"] == "Basic YUBiLmM6dG9r"
    assert bearer_network.requests_log[0].headers["authorization"] == "Bearer at"
