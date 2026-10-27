import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vimeo import VimeoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.settings import AUTH_ERROR, PERMISSION_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.source import VimeoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.vimeo import VimeoResumeConfig


def driver() -> SourceDriver:
    return SourceDriver(VimeoSource(), VimeoSourceConfig(access_token="test-token"))


@pytest.mark.parametrize(
    "endpoint,path", [("videos", "/me/videos"), ("folders", "/me/projects"), ("showcases", "/me/albums")]
)
@pytest.mark.parametrize("incremental", [False, True])
def test_pagination_and_full_refresh_params(endpoint: str, path: str, incremental: bool) -> None:
    next_url = f"{path}?page=2&per_page=100&sort=date&direction=asc"
    result = driver().run(
        endpoint,
        [
            ScriptedResponse(json={"data": [{"uri": "/resource/1"}], "paging": {"next": next_url}}),
            ScriptedResponse(json={"data": [{"uri": "/resource/2"}], "paging": {"next": None}}),
        ],
        incremental_field="date_modified" if incremental else None,
        db_incremental_field_last_value="2025-01-01T00:00:00Z" if incremental else None,
    )

    assert result.rows == [{"uri": "/resource/1"}, {"uri": "/resource/2"}]
    assert len(result.requests) == 2
    for index, request in enumerate(result.requests, start=1):
        assert request.url.startswith(f"https://api.vimeo.com{path}?")
        assert request.path == path
        assert request.query == {
            "page": (str(index),),
            "per_page": ("100",),
            "sort": ("date",),
            "direction": ("asc",),
        }
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.headers["accept"] == "application/vnd.vimeo.*+json;version=3.4"
    assert result.saved_states == [VimeoResumeConfig(next_url=f"https://api.vimeo.com{next_url}")]
    assert result.response is not None
    assert result.response.primary_keys == ["uri"]


@pytest.mark.parametrize("resume", [None, "https://api.vimeo.com/me/videos?page=4&per_page=100"])
def test_resume_and_empty_terminal_page(resume: str | None) -> None:
    result = driver().run(
        "videos",
        [ScriptedResponse(json={"data": [], "paging": {"next": None}})],
        resume_state=VimeoResumeConfig(next_url=resume) if resume else None,
    )

    assert result.rows == []
    assert result.params("page") == (["4"] if resume else ["1"])
    assert len(result.requests) == 1
    assert result.saved_states == []


@pytest.mark.parametrize("status,message", [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_error_mapping(status: int, message: str) -> None:
    result = driver().run("videos", always(ScriptedResponse(status=status, json={"error": "Access denied"})))

    assert isinstance(result.raised, HTTPError)
    assert any(
        key in str(result.raised) and value == message
        for key, value in VimeoSource().get_non_retryable_errors().items()
    )
    assert len(result.requests) == 1


@pytest.mark.parametrize("resume_url", ["https://example.com/videos?page=2", "http://api.vimeo.com/me/videos?page=2"])
def test_resume_cannot_send_token_to_another_origin(resume_url: str) -> None:
    result = driver().run("videos", [], resume_state=VimeoResumeConfig(next_url=resume_url))

    assert isinstance(result.raised, ValueError)
    assert "Refusing to send request" in str(result.raised)
    assert result.requests == []


def parent(uri: str, connection: str, link: dict[str, object] | None) -> dict[str, object]:
    return {"uri": uri, "name": "ignored", "metadata": {"connections": {connection: link} if link else {}}}


@pytest.mark.parametrize(
    "endpoint,parent_path,connection,parent_column,child_query",
    [
        ("folder_videos", "/me/projects", "videos", "folder_uri", {"sort": ("date",), "direction": ("asc",)}),
        ("showcase_videos", "/me/albums", "videos", "showcase_uri", {"sort": ("date",), "direction": ("asc",)}),
        ("video_comments", "/me/videos", "comments", "video_uri", {"direction": ("asc",)}),
        ("video_likes", "/me/videos", "likes", "video_uri", {"sort": ("date",), "direction": ("asc",)}),
    ],
)
def test_fanout_skips_empty_parents_and_tags_child_rows(
    endpoint: str, parent_path: str, connection: str, parent_column: str, child_query: dict[str, tuple[str]]
) -> None:
    child_path = f"/parents/7/{connection}"
    result = driver().run(
        endpoint,
        route(
            {
                parent_path: [
                    ScriptedResponse(
                        json={
                            "data": [
                                parent("/parents/5", connection, {"uri": f"/parents/5/{connection}", "total": 0}),
                                parent("/parents/6", connection, None),
                                parent("/parents/7", connection, {"uri": child_path, "total": 3}),
                            ],
                            "paging": {"next": None},
                        }
                    )
                ],
                child_path: [
                    ScriptedResponse(
                        json={"data": [{"uri": "/child/1"}], "paging": {"next": f"{child_path}?page=2&per_page=100"}}
                    ),
                    ScriptedResponse(json={"data": [{"uri": "/child/2"}], "paging": {"next": None}}),
                ],
            }
        ),
    )

    assert result.raised is None
    assert result.rows == [
        {"uri": "/child/1", parent_column: "/parents/7"},
        {"uri": "/child/2", parent_column: "/parents/7"},
    ]
    assert [request.path for request in result.requests] == [parent_path, child_path, child_path]
    assert result.requests[0].query["fields"] == (
        f"uri,metadata.connections.{connection}.uri,metadata.connections.{connection}.total",
    )
    assert result.requests[1].query == {"page": ("1",), "per_page": ("100",), **child_query}
    for request in result.requests:
        assert request.headers["authorization"] == "Bearer test-token"


def test_comment_replies_walk_videos_then_comments() -> None:
    result = driver().run(
        "video_comment_replies",
        route(
            {
                "/me/videos": [
                    ScriptedResponse(
                        json={
                            "data": [parent("/videos/1", "comments", {"uri": "/videos/1/comments", "total": 2})],
                            "paging": {"next": None},
                        }
                    )
                ],
                "/videos/1/comments": [
                    ScriptedResponse(
                        json={
                            "data": [
                                parent(
                                    "/videos/1/comments/10",
                                    "replies",
                                    {"uri": "/videos/1/comments/10/replies", "total": 0},
                                ),
                                parent(
                                    "/videos/1/comments/11",
                                    "replies",
                                    {"uri": "/videos/1/comments/11/replies", "total": 1},
                                ),
                            ],
                            "paging": {"next": None},
                        }
                    )
                ],
                "/videos/1/comments/11/replies": [
                    ScriptedResponse(json={"data": [{"uri": "/videos/1/comments/12"}], "paging": {"next": None}})
                ],
            }
        ),
    )

    assert result.raised is None
    assert result.rows == [{"uri": "/videos/1/comments/12", "comment_uri": "/videos/1/comments/11"}]
    assert [request.path for request in result.requests] == [
        "/me/videos",
        "/videos/1/comments",
        "/videos/1/comments/11/replies",
    ]
    assert result.requests[1].query["fields"] == (
        "uri,metadata.connections.replies.uri,metadata.connections.replies.total",
    )


def test_fanout_resumes_after_completed_parents_and_ignores_deleted_parent() -> None:
    result = driver().run(
        "video_likes",
        route(
            {
                "/me/videos": [
                    ScriptedResponse(
                        json={
                            "data": [
                                parent("/videos/1", "likes", {"uri": "/videos/1/likes", "total": 1}),
                                parent("/videos/2", "likes", {"uri": "/videos/2/likes", "total": 1}),
                                parent("/videos/3", "likes", {"uri": "/videos/3/likes", "total": 1}),
                            ],
                            "paging": {"next": None},
                        }
                    )
                ],
                "/videos/2/likes": [
                    ScriptedResponse(status=404, json={"error": "The requested video couldn't be found."})
                ],
                "/videos/3/likes": [ScriptedResponse(json={"data": [{"uri": "/users/9"}], "paging": {"next": None}})],
            }
        ),
        resume_state=VimeoResumeConfig(completed=["/videos/1/likes"]),
    )

    assert result.raised is None
    assert result.rows == [{"uri": "/users/9", "video_uri": "/videos/3"}]
    assert [request.path for request in result.requests] == ["/me/videos", "/videos/2/likes", "/videos/3/likes"]
    assert result.saved_states[-1] == VimeoResumeConfig(
        completed=["/videos/1/likes", "/videos/2/likes", "/videos/3/likes"]
    )
