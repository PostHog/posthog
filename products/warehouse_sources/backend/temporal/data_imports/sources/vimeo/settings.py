from posthog.dataclasses import frozen

BASE_URL = "https://api.vimeo.com"
PAGE_SIZE = 100
PRIMARY_KEYS = ["uri"]

ENDPOINTS = {
    "videos": "/me/videos",
    "folders": "/me/projects",
    "showcases": "/me/albums",
}


@frozen
class VimeoFanout:
    parent: str
    # The parent's `metadata.connections` entry. Its `uri` is the child list path and its `total`
    # lets a parent with an empty child list be skipped without a request.
    connection: str
    parent_uri_column: str
    primary_keys: list[str]
    params: dict[str, str]


FANOUT_ENDPOINTS = {
    "folder_videos": VimeoFanout(
        parent="folders",
        connection="videos",
        parent_uri_column="folder_uri",
        primary_keys=["folder_uri", "uri"],
        params={"sort": "date", "direction": "asc"},
    ),
    "showcase_videos": VimeoFanout(
        parent="showcases",
        connection="videos",
        parent_uri_column="showcase_uri",
        primary_keys=["showcase_uri", "uri"],
        params={"sort": "date", "direction": "asc"},
    ),
    "video_comments": VimeoFanout(
        parent="videos",
        connection="comments",
        parent_uri_column="video_uri",
        primary_keys=["uri"],
        params={"direction": "asc"},
    ),
    "video_comment_replies": VimeoFanout(
        parent="video_comments",
        connection="replies",
        parent_uri_column="comment_uri",
        primary_keys=["uri"],
        params={},
    ),
    "video_likes": VimeoFanout(
        parent="videos",
        connection="likes",
        parent_uri_column="video_uri",
        primary_keys=["video_uri", "uri"],
        params={"sort": "date", "direction": "asc"},
    ),
}

AUTH_ERROR = "Vimeo rejected your access token. Generate an authenticated token for your account and reconnect."
PERMISSION_ERROR = (
    "Vimeo denied access. Check your account permissions and enable the token's public and private scopes."
)
