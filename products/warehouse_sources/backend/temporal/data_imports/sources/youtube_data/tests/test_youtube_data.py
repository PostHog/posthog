from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.youtubedata import (
    YoutubeDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_data.source import YoutubeDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_data.youtube_data import (
    YoutubeDataResumeConfig,
)


@pytest.fixture
def driver() -> SourceDriver:
    return SourceDriver(YoutubeDataSource(), YoutubeDataSourceConfig(api_key="fake-api-key", channel_id="UC_example"))


def page(items: list[dict[str, Any]], next_token: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"items": items}
    if next_token is not None:
        body["nextPageToken"] = next_token
    return ScriptedResponse(json=body)


@pytest.mark.parametrize(
    ("table", "filter_name", "path"),
    [
        ("channels", "id", "channels"),
        ("playlists", "channelId", "playlists"),
        ("comment_threads", "allThreadsRelatedToChannelId", "commentThreads"),
    ],
)
def test_public_snapshots_keep_channel_filter_through_empty_pages(
    driver: SourceDriver, table: str, filter_name: str, path: str
) -> None:
    first = {"id": "first", "snippet": {"title": "Example"}}
    last = {"id": "last", "statistics": {"viewCount": "42"}}
    result = driver.run(table, [page([first], "second"), page([], "third"), page([last])])

    assert result.raised is None
    assert result.rows == [first, last]
    assert result.paths == [f"/youtube/v3/{path}"] * 3
    assert result.params(filter_name) == ["UC_example"] * 3
    assert result.params("key") == ["fake-api-key"] * 3
    assert result.params("pageToken") == [None, "second", "third"]
    assert result.params("publishedAfter") == [None] * 3
    assert result.committed_states == [
        YoutubeDataResumeConfig(paginator_state={"cursor": "second"}),
        YoutubeDataResumeConfig(paginator_state={"cursor": "third"}),
    ]


def test_resume_starts_at_saved_page_token(driver: SourceDriver) -> None:
    result = driver.run(
        "playlists",
        [page([{"id": "last"}])],
        resume_state=YoutubeDataResumeConfig(paginator_state={"cursor": "saved-page"}),
    )

    assert result.raised is None
    assert result.params("pageToken") == ["saved-page"]
    assert result.rows == [{"id": "last"}]


@pytest.mark.parametrize("resuming", [False, True])
def test_playlist_items_keep_separate_parent_cursors(driver: SourceDriver, resuming: bool) -> None:
    parent_path = "playlistItems?playlistId=playlist-a"
    resume = YoutubeDataResumeConfig(
        paginator_state={"completed": [], "current": parent_path, "child_state": {"cursor": "next-items"}}
    )
    script = [page([{"id": "playlist-a"}, {"id": "playlist-b"}], "more-playlists")]
    if not resuming:
        script.append(page([{"id": "item-first"}], "next-items"))
    script.extend([page([{"id": "item-last"}]), page([]), page([{"id": "playlist-c"}]), page([{"id": "item-c"}])])

    result = driver.run("playlist_items", script, resume_state=resume if resuming else None)

    assert result.raised is None
    assert result.rows == ([] if resuming else [{"id": "item-first", "playlist_id": "playlist-a"}]) + [
        {"id": "item-last", "playlist_id": "playlist-a"},
        {"id": "item-c", "playlist_id": "playlist-c"},
    ]
    child_requests = [request for request in result.requests if request.path.endswith("/playlistItems")]
    assert [request.param("playlistId") for request in child_requests] == (
        ["playlist-a", "playlist-b", "playlist-c"]
        if resuming
        else ["playlist-a", "playlist-a", "playlist-b", "playlist-c"]
    )
    assert [request.param("pageToken") for request in child_requests] == (
        ["next-items", None, None] if resuming else [None, "next-items", None, None]
    )
    assert all(request.param("playlist_id") is None for request in child_requests)
    assert result.params("pageToken")[-2] == "more-playlists"
    assert result.committed_states[-1].paginator_state == {
        "completed": [
            "playlistItems?playlistId=playlist-a",
            "playlistItems?playlistId=playlist-b",
            "playlistItems?playlistId=playlist-c",
        ],
        "current": None,
        "child_state": None,
    }


@pytest.mark.parametrize("resuming", [False, True])
def test_videos_use_uploads_playlist_without_search_or_invalid_page_size(driver: SourceDriver, resuming: bool) -> None:
    resume = YoutubeDataResumeConfig(
        paginator_state={"completed": ["videos?id=video-a"], "current": None, "child_state": None}
    )
    script = [
        page([{"id": "UC_example", "contentDetails": {"relatedPlaylists": {"uploads": "uploads-example"}}}]),
        page([{"contentDetails": {"videoId": "video-a"}}, {"contentDetails": {"videoId": "video-b"}}], "next-uploads"),
    ]
    if not resuming:
        script.append(page([{"id": "video-a", "statistics": {"viewCount": "100"}}]))
    script.extend([page([]), page([{"contentDetails": {"videoId": "video-c"}}]), page([{"id": "video-c"}])])

    result = driver.run("videos", script, resume_state=resume if resuming else None)

    assert result.raised is None
    assert result.rows == ([] if resuming else [{"id": "video-a", "statistics": {"viewCount": "100"}}]) + [
        {"id": "video-c"}
    ]
    video_requests = [request for request in result.requests if request.path.endswith("/videos")]
    assert [request.param("id") for request in video_requests] == (
        ["video-b", "video-c"] if resuming else ["video-a", "video-b", "video-c"]
    )
    assert all(request.param("maxResults") is None for request in video_requests)
    assert all(request.param("video_id") is None for request in video_requests)
    uploads_requests = [request for request in result.requests if request.path.endswith("/playlistItems")]
    assert [request.param("playlistId") for request in uploads_requests] == ["uploads-example"] * 2
    assert [request.param("pageToken") for request in uploads_requests] == [None, "next-uploads"]
    assert not any(request.path.endswith("/search") for request in result.requests)
    assert result.committed_states[-1].paginator_state == {
        "completed": ["videos?id=video-a", "videos?id=video-b", "videos?id=video-c"],
        "current": None,
        "child_state": None,
    }


@pytest.mark.parametrize("body", [{"items": []}, {"items": [{"id": "UC_example"}]}])
def test_missing_channel_or_uploads_fails_before_video_discovery(driver: SourceDriver, body: dict[str, Any]) -> None:
    result = driver.run("videos", [ScriptedResponse(json=body)])

    assert isinstance(result.raised, ValueError)
    assert "was not found" in str(result.raised)
    assert result.rows == []
    assert result.paths == ["/youtube/v3/channels"]
