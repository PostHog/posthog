"""Static test-file census of a connected repo, resolved through its owners.yaml map.

One tarball request per repo per run (the stream carries both the path list and the
ownership files), captured as one ``eng_analytics_test_census`` event per owning team
into the team's own project.
"""

import shutil
import tarfile
import tempfile
import posixpath
from contextlib import closing
from pathlib import Path

from posthog_owners import TeamTestCensus, census, runner_for_path

from posthog.api.capture import capture_batch_internal
from posthog.egress.github.transport import github_request, raise_if_github_rate_limited
from posthog.models.integration.github import _is_safe_github_repo_path
from posthog.models.team import Team

CENSUS_EVENT = "eng_analytics_test_census"
_GITHUB_API = "https://api.github.com"
# owners.yaml and product.yaml are hand-written config; anything bigger is not one.
_MAX_OWNERSHIP_FILE_BYTES = 512 * 1024
_OWNERSHIP_BASENAMES = {"owners.yaml", "product.yaml"}


def collect_repo_census(repository: str, access_token: str, *, timeout: int = 300) -> list[TeamTestCensus]:
    """Stream the repo tarball once, keeping only test-file paths and the ownership files."""
    if not _is_safe_github_repo_path(repository):
        raise ValueError(f"Unsafe GitHub repo path: {repository!r}")
    url = f"{_GITHUB_API}/repos/{repository}/tarball"
    with tempfile.TemporaryDirectory(prefix="owners-census-") as tmp:
        root = Path(tmp)
        test_paths: list[str] = []
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
                    if runner_for_path(rel) is not None:
                        test_paths.append(rel)
                    if posixpath.basename(rel) not in _OWNERSHIP_BASENAMES:
                        continue
                    if member.size > _MAX_OWNERSHIP_FILE_BYTES:
                        continue
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        continue
                    target = root / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("wb") as handle:
                        shutil.copyfileobj(extracted, handle)
        return census(test_paths, root)


def emit_census_events(team: Team, repository: str, rows: list[TeamTestCensus]) -> None:
    result = capture_batch_internal(
        events=[
            {
                "event": CENSUS_EVENT,
                "distinct_id": f"eng_analytics_census:{repository}",
                "properties": {"repository": repository, **row.as_payload()},
            }
            for row in rows
        ],
        token=team.api_token,
        event_source="engineering_analytics_census",
        process_person_profile=False,
    )
    result.raise_for_status()
