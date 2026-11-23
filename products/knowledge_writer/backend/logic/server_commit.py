import base64
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import quote

from posthog.dataclasses import frozen
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError

from .docs_pages import ancestor_directories
from .writer_change import WriterChange

REGULAR_FILE_MODE = 0o100644
DIRECTORY_MODE = 0o040000
REGULAR_FILE_TREE_MODE = "100644"
GRAPHQL_TIMEOUT_SECONDS = 60
COMMIT_TIMEOUT_SECONDS = 60
BASE_TREE_BATCH_PATHS = 100

DEFAULT_BRANCH_HEAD_QUERY = """query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { defaultBranchRef { target { oid } } }
}"""


class DocsCommitFailed(Exception):
    pass


@frozen
class CommitIdentity:
    name: str
    email: str


@frozen
class BaseEntry:
    mode: int
    oid: str


@frozen
class BaseTree:
    entries: Mapping[str, BaseEntry | None]
    texts: Mapping[str, str | None]


def docs_branch_head(github: GitHubIntegration, docs_repository: str) -> str | None:
    owner, name = docs_repository.split("/", 1)
    repository = github._gh_graphql(
        DEFAULT_BRANCH_HEAD_QUERY, {"owner": owner, "name": name}, endpoint="/graphql:knowledgeWriterBaseHead"
    ).get("repository")
    if repository is None:
        return None
    target = (repository.get("defaultBranchRef") or {}).get("target") or {}
    oid = target.get("oid")
    if not isinstance(oid, str):
        raise GitHubIntegrationError(f"knowledge writer could not read the default branch head of {docs_repository}")
    return oid


def base_tree(github: GitHubIntegration, docs_repository: str, base_sha: str, paths: frozenset[str]) -> BaseTree:
    directories = sorted({directory for path in paths for directory in ancestor_directories(path)})
    texts_wanted = sorted(paths)
    expressions_by_alias: dict[str, str] = {
        **{f"d{index}": f"{base_sha}:{directory}" for index, directory in enumerate(directories)},
        **{f"t{index}": f"{base_sha}:{path}" for index, path in enumerate(texts_wanted)},
    }
    aliases = list(expressions_by_alias)
    owner, name = docs_repository.split("/", 1)
    repository: dict = {}
    for batch_start in range(0, len(aliases), BASE_TREE_BATCH_PATHS):
        batch_aliases = aliases[batch_start : batch_start + BASE_TREE_BATCH_PATHS]
        repository.update(
            base_tree_objects(
                github,
                base_tree_query(batch_aliases),
                {"owner": owner, "name": name, **{alias: expressions_by_alias[alias] for alias in batch_aliases}},
            )
        )
    listed: dict[str, BaseEntry] = {}
    for index, directory in enumerate(directories):
        for entry in (repository.get(f"d{index}") or {}).get("entries") or []:
            listed[f"{directory}/{entry['name']}" if directory else entry["name"]] = BaseEntry(
                mode=int(entry["mode"]), oid=str(entry["oid"])
            )
    every_path = paths | {directory for directory in directories if directory}
    return BaseTree(
        entries={path: listed.get(path) for path in every_path},
        texts={
            path: blob_text(github, docs_repository, repository.get(f"t{index}"))
            for index, path in enumerate(texts_wanted)
        },
    )


def base_tree_query(aliases: list[str]) -> str:
    declared = "".join(f", ${alias}: String!" for alias in aliases)
    selected = " ".join(
        f"{alias}: object(expression: ${alias}) {{ ... on Tree {{ entries {{ name mode oid }} }} }}"
        if alias.startswith("d")
        else f"{alias}: object(expression: ${alias}) {{ ... on Blob {{ oid text isBinary isTruncated }} }}"
        for alias in aliases
    )
    return f"query($owner: String!, $name: String!{declared}) {{ repository(owner: $owner, name: $name) {{ {selected} }} }}"


def base_tree_objects(github: GitHubIntegration, query: str, variables: dict[str, str]) -> dict:
    response = github.api_request(
        "POST",
        "/graphql",
        endpoint="/graphql:knowledgeWriterBaseTree",
        json_body={"query": query, "variables": variables},
        timeout=GRAPHQL_TIMEOUT_SECONDS,
        retry_transient=True,
    )
    if response.status_code != 200:
        raise DocsCommitFailed(f"knowledge writer could not read the docs base tree: {response.status_code}")
    body = response.json()
    repository = (body.get("data") or {}).get("repository")
    if body.get("errors") or not isinstance(repository, dict):
        raise DocsCommitFailed("knowledge writer could not read the whole docs base tree")
    return repository


def blob_text(github: GitHubIntegration, docs_repository: str, blob: object) -> str | None:
    if not isinstance(blob, dict) or blob.get("isBinary"):
        return None
    if blob.get("isTruncated"):
        return full_blob_text(github, docs_repository, str(blob["oid"]))
    text = blob.get("text")
    return text if isinstance(text, str) else None


def full_blob_text(github: GitHubIntegration, docs_repository: str, oid: str) -> str | None:
    response = github.api_request(
        "GET",
        f"/repos/{docs_repository}/git/blobs/{oid}",
        endpoint="/repos/{owner}/{repo}/git/blobs/{file_sha}",
        timeout=COMMIT_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise DocsCommitFailed(f"knowledge writer could not read a docs base blob: {response.status_code}")
    try:
        return base64.b64decode(response.json()["content"]).decode("utf-8")
    except UnicodeDecodeError:
        return None


def build_commit(
    github: GitHubIntegration,
    docs_repository: str,
    change: WriterChange,
    base_sha: str,
    *,
    author: CommitIdentity,
    committed_at: datetime,
    message: str,
) -> str:
    base_commit = github.api_request(
        "GET",
        f"/repos/{docs_repository}/git/commits/{base_sha}",
        endpoint="/repos/{owner}/{repo}/git/commits/{commit_sha}",
    )
    if base_commit.status_code != 200:
        raise DocsCommitFailed(f"knowledge writer could not read the docs base commit: {base_commit.status_code}")
    tree = github.api_request(
        "POST",
        f"/repos/{docs_repository}/git/trees",
        endpoint="/repos/{owner}/{repo}/git/trees",
        json_body={"base_tree": base_commit.json()["tree"]["sha"], "tree": tree_entries(change)},
        timeout=COMMIT_TIMEOUT_SECONDS,
        retry_transient=True,
    )
    if tree.status_code != 201:
        raise DocsCommitFailed(f"knowledge writer could not create its docs tree: {tree.status_code}")
    signature = {"name": author.name, "email": author.email, "date": git_date(committed_at)}
    commit = github.api_request(
        "POST",
        f"/repos/{docs_repository}/git/commits",
        endpoint="/repos/{owner}/{repo}/git/commits",
        json_body={
            "message": message,
            "tree": tree.json()["sha"],
            "parents": [base_sha],
            "author": signature,
            "committer": signature,
        },
        timeout=COMMIT_TIMEOUT_SECONDS,
        retry_transient=True,
    )
    if commit.status_code != 201:
        raise DocsCommitFailed(f"knowledge writer could not create its docs commit: {commit.status_code}")
    return str(commit.json()["sha"])


def tree_entries(change: WriterChange) -> list[dict[str, str | None]]:
    written: list[dict[str, str | None]] = [
        {"path": path, "mode": REGULAR_FILE_TREE_MODE, "type": "blob", "content": content.decode("utf-8")}
        for path, content in change.written.items()
    ]
    deleted: list[dict[str, str | None]] = [
        {"path": path, "mode": REGULAR_FILE_TREE_MODE, "type": "blob", "sha": None} for path in change.deleted
    ]
    return sorted([*written, *deleted], key=lambda entry: str(entry["path"]))


def git_date(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def publish_ref(github: GitHubIntegration, docs_repository: str, head_branch: str, commit_sha: str) -> bool:
    created = github.api_request(
        "POST",
        f"/repos/{docs_repository}/git/refs",
        endpoint="/repos/{owner}/{repo}/git/refs",
        json_body={"ref": f"refs/heads/{head_branch}", "sha": commit_sha},
    )
    if created.status_code == 201:
        return True
    if created.status_code != 422:
        raise DocsCommitFailed(f"knowledge writer could not create its docs branch: {created.status_code}")
    existing = github.api_request(
        "GET",
        f"/repos/{docs_repository}/git/ref/heads/{quote(head_branch, safe='/')}",
        endpoint="/repos/{owner}/{repo}/git/ref/heads/{branch}",
    )
    if existing.status_code != 200:
        raise DocsCommitFailed(f"knowledge writer could not read its docs branch: {existing.status_code}")
    return existing.json()["object"]["sha"] == commit_sha
