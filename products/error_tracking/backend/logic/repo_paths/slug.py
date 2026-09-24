"""Turn a release's git remote URL into the repo slug that names its file list.

Cymbal parses the same remote URL for the same release (``rust/cymbal`` ``repo_paths/slug.rs``),
and both sides must produce the same slug, or the service looks for a list under the wrong key.
Both implementations run the cases in ``rust/cymbal/tests/static/repo_slug_cases.json``.
"""

import re

from posthog.dataclasses import frozen

_URL_SCHEMES = ("https://", "http://", "ssh://")
_SCP_RE = re.compile(r"^[^@/:]+@(?P<host>[^@/:]+):(?P<path>.+)$")
_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._~+-]+$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


@frozen
class RepoSlug:
    host: str
    path: str

    def __str__(self) -> str:
        return f"{self.host}/{self.path}"


def repo_slug(remote_url: str) -> RepoSlug | None:
    url = remote_url.strip()
    if not url or any(char.isspace() or char in "?#" for char in url):
        return None

    scheme = next((s for s in _URL_SCHEMES if url.lower().startswith(s)), None)
    if scheme is not None:
        authority, slash, path = url[len(scheme) :].partition("/")
        if not slash:
            return None
        host = authority.rpartition("@")[2].partition(":")[0]
    else:
        match = _SCP_RE.match(url)
        if match is None:
            return None
        host, path = match["host"], match["path"]

    host = host.lower()
    path = path.rstrip("/").removesuffix(".git").removeprefix("/")
    segments = path.split("/")
    if not _HOST_RE.match(host) or len(segments) < 2:
        return None
    if any(segment in (".", "..") or not _SEGMENT_RE.match(segment) for segment in segments):
        return None
    return RepoSlug(host=host, path=path)


def is_full_commit_sha(commit: object) -> bool:
    return isinstance(commit, str) and _COMMIT_RE.match(commit) is not None
