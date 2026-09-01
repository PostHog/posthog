import io
import tarfile
from types import SimpleNamespace

from unittest.mock import patch

from posthog_owners import TeamTestCensus

from products.engineering_analytics.backend.logic.census import CENSUS_EVENT, collect_repo_census, emit_census_events


def _tarball(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class _RawBody(io.BytesIO):
    decode_content = False


class _FakeTarballResponse:
    status_code = 200
    headers: dict[str, str] = {}

    def __init__(self, body: bytes) -> None:
        self.raw = _RawBody(body)

    def raise_for_status(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_collect_repo_census_strips_the_tarball_prefix_and_ignores_traversal_members() -> None:
    body = _tarball(
        {
            "PostHog-posthog-abc123/owners.yaml": b"version: 1\nowners: []\n",
            "PostHog-posthog-abc123/products/a/owners.yaml": b"version: 1\nowners: [team-a]\n",
            "PostHog-posthog-abc123/products/a/test_api.py": b"",
            "PostHog-posthog-abc123/products/a/thing.test.tsx": b"",
            "PostHog-posthog-abc123/posthog/test_uncovered.py": b"",
            "PostHog-posthog-abc123/../escape/test_evil.py": b"",
        }
    )
    with patch(
        "products.engineering_analytics.backend.logic.census.github_request",
        return_value=_FakeTarballResponse(body),
    ):
        rows = collect_repo_census("PostHog/posthog", "token")

    assert [(r.owner_team, r.pytest_file_count, r.jest_file_count) for r in rows] == [
        ("team-a", 1, 1),
        ("unowned", 1, 0),
    ]


def test_emit_census_events_captures_the_contract_layer_4_reads() -> None:
    team = SimpleNamespace(api_token="phc_test")
    rows = [TeamTestCensus(owner_team="team-a", pytest_file_count=1, jest_file_count=0)]

    with patch("products.engineering_analytics.backend.logic.census.capture_batch_internal") as capture:
        emit_census_events(team, "PostHog/posthog", rows)  # type: ignore[arg-type]

    kwargs = capture.call_args.kwargs
    assert kwargs["token"] == "phc_test"
    assert kwargs["events"] == [
        {
            "event": CENSUS_EVENT,
            "distinct_id": "eng_analytics_census:PostHog/posthog",
            "properties": {
                "repository": "PostHog/posthog",
                "owner_team": "team-a",
                "pytest_file_count": 1,
                "jest_file_count": 0,
                "test_file_count": 1,
            },
        }
    ]
