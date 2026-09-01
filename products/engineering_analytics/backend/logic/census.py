"""Static test-file census of a connected repo, resolved through its owners.yaml map.

One tarball request per repo per run (the stream carries both the path list and the
ownership files), captured as one ``eng_analytics_test_census`` event per owning team
into the team's own project.
"""

import tarfile
import tempfile
import posixpath
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from posthog_owners import TeamTestCensus, census

from posthog.api.capture import capture_internal
from posthog.egress.github.transport import github_request, raise_if_github_rate_limited
from posthog.models.team import Team

from products.engineering_analytics.backend.logic.job_logs.fetcher import _is_safe_github_repo_path

CENSUS_EVENT = "eng_analytics_test_census"
_GITHUB_API = "https://api.github.com"
# owners.yaml and product.yaml are hand-written config; anything bigger is not one.
_MAX_OWNERSHIP_FILE_BYTES = 512 * 1024
_OWNERSHIP_BASENAMES = {"owners.yaml", "product.yaml"}


@contextmanager
def _repo_snapshot(repository: str, access_token: str, *, timeout: int = 300) -> Iterator[tuple[list[str], Path]]:
    """Stream the repo tarball once, yielding every tracked path plus a temp dir holding
    only the ownership files, laid out at their repo-relative locations."""
    if not _is_safe_github_repo_path(repository):
        raise ValueError(f"Unsafe GitHub repo path: {repository!r}")
    url = f"{_GITHUB_API}/repos/{repository}/tarball"
    with tempfile.TemporaryDirectory(prefix="owners-census-") as tmp:
        root = Path(tmp)
        paths: list[str] = []
        with closing(
            github_request(
                "GET",
                url,
                source="owners_census",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=timeout,
                allow_redirects=True,
                stream=True,
            )
        ) as response:
            raise_if_github_rate_limited(response)
            response.raise_for_status()
            response.raw.decode_content = True
            with tarfile.open(fileobj=response.raw, mode="r|gz") as archive:
                for member in archive:
                    if not member.isfile():
                        continue
                    # GitHub prefixes every entry with `<owner>-<repo>-<sha>/`.
                    rel = member.name.split("/", 1)[1] if "/" in member.name else ""
                    if not rel or rel != posixpath.normpath(rel) or rel.startswith(("../", "/")):
                        continue
                    paths.append(rel)
                    if posixpath.basename(rel) not in _OWNERSHIP_BASENAMES:
                        continue
                    if member.size > _MAX_OWNERSHIP_FILE_BYTES:
                        continue
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        continue
                    target = root / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(extracted.read())
        yield paths, root


def collect_repo_census(repository: str, access_token: str) -> list[TeamTestCensus]:
    with _repo_snapshot(repository, access_token) as (paths, root):
        return census(paths, root)


def emit_census_events(team: Team, repository: str, rows: list[TeamTestCensus]) -> None:
    for row in rows:
        capture_internal(
            token=team.api_token,
            event_name=CENSUS_EVENT,
            event_source="engineering_analytics_census",
            distinct_id=f"eng_analytics_census:{repository}",
            properties={
                "repository": repository,
                "owner_team": row.owner_team,
                "pytest_file_count": row.pytest_file_count,
                "jest_file_count": row.jest_file_count,
                "test_file_count": row.test_file_count,
            },
        )
