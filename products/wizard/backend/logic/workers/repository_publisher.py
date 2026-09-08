import shlex
import base64
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.integration import GitHubIntegration, Integration

from products.tasks.backend.facade.sandbox import SandboxBase, sandbox_repo_path
from products.wizard.backend.logic.workers.commands import bound_command_output
from products.wizard.backend.logic.workers.contracts import RepositoryPullRequest, SignedRepositoryCommit

GIT_COMMAND_TIMEOUT_SECONDS = 60
GITHUB_MUTATION_TIMEOUT_SECONDS = 60
MAX_COMMIT_PAYLOAD_BYTES = 35 * 1024 * 1024

_CREATE_COMMIT_MUTATION = """mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid url } }
}"""
_CREATE_BRANCH_MUTATION = """mutation($input: CreateRefInput!) {
  createRef(input: $input) { ref { name } }
}"""
_BRANCH_TIP_QUERY = """query($owner: String!, $name: String!, $qualifiedName: String!) {
  repository(owner: $owner, name: $name) {
    id
    ref(qualifiedName: $qualifiedName) {
      target { ... on Commit { oid } }
    }
  }
}"""


class RepositoryPublishingError(Exception):
    pass


@frozen
class _RepositoryName:
    owner: str
    name: str


@frozen
class _StagedChanges:
    additions: list[tuple[str, str]]
    deletions: list[str]


def create_signed_commit(
    sandbox: SandboxBase,
    *,
    team_id: int,
    integration_id: int,
    repository: str,
    branch: str,
    message: str,
    source: str,
) -> SignedRepositoryCommit:
    """Create a signed commit through GitHub without requiring a local signing key."""
    repository_path = sandbox_repo_path(repository)
    repository_name = _repository_parts(repository)
    github = _github_integration(team_id, integration_id, source)

    _stage_all(sandbox, repository_path)
    head_sha = _head_sha(sandbox, repository_path)

    repository_id, existing_tip = _repository_and_branch_tip(
        github, repository_name.owner, repository_name.name, branch
    )
    if existing_tip is None:
        branch_existed = False
        _create_branch(github, repository_id, branch, head_sha)
        branch_tip = head_sha
    else:
        branch_existed = True
        _fetch_branch(sandbox, repository_path, branch)
        branch_tip = existing_tip

    changes = _staged_changes(sandbox, repository_path, branch_tip)
    if not changes.additions and not changes.deletions:
        if branch_existed:
            return SignedRepositoryCommit(repository=repository, branch=branch, commit_shas=(branch_tip,))
        raise RepositoryPublishingError("No staged changes to commit.")

    _assert_payload_size(changes)
    commit_sha = _commit_staged_changes(github, repository, branch, branch_tip, message, changes)
    return SignedRepositoryCommit(repository=repository, branch=branch, commit_shas=(commit_sha,))


def _stage_all(sandbox: SandboxBase, repository_path: str) -> None:
    _run_git(sandbox, repository_path, "add --all", "staging")


def _head_sha(sandbox: SandboxBase, repository_path: str) -> str:
    head_sha = _run_git(sandbox, repository_path, "rev-parse HEAD", "HEAD resolution").strip()
    if not head_sha:
        raise RepositoryPublishingError("Repository checkout has no HEAD commit.")
    return head_sha


def _fetch_branch(sandbox: SandboxBase, repository_path: str, branch: str) -> None:
    _run_git(sandbox, repository_path, f"fetch --no-tags origin {shlex.quote(branch)}", "branch fetch")


def _staged_changes(sandbox: SandboxBase, repository_path: str, branch_tip: str) -> _StagedChanges:
    output = _run_git(
        sandbox,
        repository_path,
        f"diff --cached -z --no-renames --name-status {shlex.quote(branch_tip)}",
        "staged change detection",
    )

    additions: list[tuple[str, str]] = []
    deletions: list[str] = []
    tokens = output.split("\0")
    remaining_bytes = MAX_COMMIT_PAYLOAD_BYTES
    for index in range(0, len(tokens) - 1, 2):
        status, path = tokens[index], tokens[index + 1]
        if not status:
            continue
        if status.startswith("D"):
            remaining_bytes -= len(path.encode("utf-8")) + 16
            deletions.append(path)
        else:
            remaining_bytes -= len(path.encode("utf-8")) + 32
            if remaining_bytes < 0:
                raise RepositoryPublishingError("Staged changes exceed the GitHub commit payload limit.")
            contents = _staged_file_contents(sandbox, repository_path, path, remaining_bytes)
            remaining_bytes -= len(contents)
            additions.append((path, contents))
        if remaining_bytes < 0:
            raise RepositoryPublishingError("Staged changes exceed the GitHub commit payload limit.")
    return _StagedChanges(additions=additions, deletions=deletions)


def _staged_file_contents(sandbox: SandboxBase, repository_path: str, path: str, remaining_bytes: int) -> str:
    contents = _run_git(
        sandbox,
        repository_path,
        f"show {shlex.quote(f':{path}')} | base64 -w 0",
        f"staged file read for '{path}'",
        max_output_bytes=remaining_bytes,
    ).strip()
    try:
        base64.b64decode(contents, validate=True)
    except ValueError as error:
        raise RepositoryPublishingError(f"Could not read staged file '{path}'.") from error
    return contents


def _assert_payload_size(changes: _StagedChanges) -> None:
    payload_bytes = sum(len(path) + len(contents) + 32 for path, contents in changes.additions)
    payload_bytes += sum(len(path) + 16 for path in changes.deletions)
    if payload_bytes > MAX_COMMIT_PAYLOAD_BYTES:
        raise RepositoryPublishingError("Staged changes exceed the GitHub commit payload limit.")


def _commit_staged_changes(
    github: GitHubIntegration,
    repository: str,
    branch: str,
    branch_tip: str,
    message: str,
    changes: _StagedChanges,
) -> str:
    headline, _, body = message.partition("\n")
    payload = _graphql_request(
        github,
        _CREATE_COMMIT_MUTATION,
        {
            "input": {
                "branch": {"repositoryNameWithOwner": repository, "branchName": branch},
                "expectedHeadOid": branch_tip,
                "message": {"headline": headline.strip(), "body": body.strip()},
                "fileChanges": {
                    "additions": [{"path": path, "contents": contents} for path, contents in changes.additions],
                    "deletions": [{"path": path} for path in changes.deletions],
                },
            }
        },
        "signed commit",
    )

    commit = _payload_dict(payload, "createCommitOnBranch", "commit")
    commit_sha = commit.get("oid") if commit else None
    if not isinstance(commit_sha, str):
        raise RepositoryPublishingError("GitHub did not return the signed commit.")
    return commit_sha


def _github_integration(team_id: int, integration_id: int, source: str) -> GitHubIntegration:
    integration = Integration.objects.filter(team_id=team_id, id=integration_id, kind="github").first()
    if integration is None:
        raise RepositoryPublishingError("GitHub integration is unavailable.")
    return GitHubIntegration(integration, source=source)


def _repository_and_branch_tip(
    github: GitHubIntegration, owner: str, repository_name: str, branch: str
) -> tuple[str, str | None]:
    payload = _graphql_request(
        github,
        _BRANCH_TIP_QUERY,
        {"owner": owner, "name": repository_name, "qualifiedName": f"refs/heads/{branch}"},
        "branch tip query",
    )

    repository_data = _payload_dict(payload, "repository")
    repository_id = repository_data.get("id") if repository_data else None
    if not isinstance(repository_id, str):
        raise RepositoryPublishingError("GitHub repository is unavailable.")

    ref_data = repository_data.get("ref") if repository_data else None
    target = ref_data.get("target") if isinstance(ref_data, dict) else None
    tip = target.get("oid") if isinstance(target, dict) else None
    return repository_id, tip if isinstance(tip, str) else None


def _create_branch(github: GitHubIntegration, repository_id: str, branch: str, head_sha: str) -> None:
    _graphql_request(
        github,
        _CREATE_BRANCH_MUTATION,
        {"input": {"repositoryId": repository_id, "name": f"refs/heads/{branch}", "oid": head_sha}},
        "branch creation",
    )


def _graphql_request(
    github: GitHubIntegration, query: str, variables: dict[str, Any], endpoint_label: str
) -> dict[str, Any]:
    response = github.api_request(
        "POST",
        "/graphql",
        endpoint=endpoint_label,
        json_body={"query": query, "variables": variables},
        timeout=GITHUB_MUTATION_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise RepositoryPublishingError(f"GitHub {endpoint_label} failed with status code {response.status_code}.")
    try:
        payload: Any = response.json()
    except ValueError as error:
        raise RepositoryPublishingError(f"GitHub {endpoint_label} returned an invalid response.") from error
    if not isinstance(payload, dict):
        raise RepositoryPublishingError(f"GitHub {endpoint_label} returned an invalid response.")

    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        messages = ", ".join(
            entry["message"] for entry in errors if isinstance(entry, dict) and isinstance(entry.get("message"), str)
        )
        raise RepositoryPublishingError(f"GitHub {endpoint_label} failed: {messages}")
    return payload


def _payload_dict(payload: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    value: object = payload
    for key in ("data", *keys):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, dict) else None


def create_pull_request(
    *,
    team_id: int,
    integration_id: int,
    repository: str,
    head_branch: str,
    title: str,
    body: str,
    source: str,
) -> RepositoryPullRequest:
    repository_name = _repository_parts(repository)
    integration = Integration.objects.filter(team_id=team_id, id=integration_id, kind="github").first()
    if integration is None:
        raise RepositoryPublishingError("GitHub integration is unavailable.")

    github = GitHubIntegration(integration, source=source)
    if github.organization().casefold() != repository_name.owner.casefold():
        raise RepositoryPublishingError("GitHub integration does not own the repository.")

    base_branch = github.get_default_branch(repository_name.name)
    existing = _matching_pull_request(
        github.list_pull_requests(repository_name.name),
        repository,
        head_branch,
        base_branch,
    )
    if existing is not None:
        return existing

    created = github.create_pull_request(repository_name.name, title, body, head_branch, base_branch)
    return _created_pull_request(created, repository, head_branch, base_branch)


def _matching_pull_request(
    payload: object,
    repository: str,
    head_branch: str,
    base_branch: str,
) -> RepositoryPullRequest | None:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return None
    pull_requests = payload.get("pull_requests")
    if not isinstance(pull_requests, list):
        return None
    for value in pull_requests:
        if not isinstance(value, dict) or value.get("head_branch") != head_branch:
            continue
        number = value.get("number")
        url = value.get("url")
        pull_request_base_branch = value.get("base_branch")
        if isinstance(number, int) and isinstance(url, str):
            return RepositoryPullRequest(
                repository=repository,
                number=number,
                url=url,
                head_branch=head_branch,
                base_branch=pull_request_base_branch if isinstance(pull_request_base_branch, str) else base_branch,
            )
    return None


def _created_pull_request(
    payload: object,
    repository: str,
    head_branch: str,
    base_branch: str,
) -> RepositoryPullRequest:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RepositoryPublishingError("GitHub did not create the pull request.")
    number = payload.get("pr_number")
    url = payload.get("pr_url")
    if not isinstance(number, int) or not isinstance(url, str):
        raise RepositoryPublishingError("GitHub returned an invalid pull request.")
    return RepositoryPullRequest(
        repository=repository,
        number=number,
        url=url,
        head_branch=head_branch,
        base_branch=base_branch,
    )


def _repository_parts(repository: str) -> _RepositoryName:
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise RepositoryPublishingError("Repository must use owner/name format.")
    return _RepositoryName(owner=parts[0], name=parts[1])


def _run_git(
    sandbox: SandboxBase,
    repository_path: str,
    arguments: str,
    stage: str,
    *,
    max_output_bytes: int = MAX_COMMIT_PAYLOAD_BYTES,
) -> str:
    command = f"git -C {shlex.quote(repository_path)} {arguments}"
    result = sandbox.execute(
        bound_command_output(command, stdout_limit=max_output_bytes + 1, tail=False),
        timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
    )
    if len(result.stdout.encode("utf-8")) > max_output_bytes:
        raise RepositoryPublishingError("Staged changes exceed the GitHub commit payload limit.")
    if result.exit_code != 0:
        raise RepositoryPublishingError(f"Repository {stage} failed with exit code {result.exit_code}.")
    return result.stdout
