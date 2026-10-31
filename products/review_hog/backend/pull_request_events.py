"""GitHub `pull_request` deliveries of the PostHog GitHub App, routed by action.

- `opened` / `synchronize` / `ready_for_review`: an automatic review (`automatic_reviews.py`).

The webhook handler runs inside the request, so this module only parses the payload, reads the
cached ownership summary, and queues a Celery task. The task checks ownership and the rules again.
"""

from collections.abc import Iterable, Mapping

from posthog.dataclasses import frozen

from products.review_hog.backend.ownership import OwnedRepositoryPrefilter, RepositoryRef

# Authors and automation apply this label to opt a pull request out of automatic reviews.
SKIP_AGENT_REVIEW_LABEL = "skip-agent-review"
AUTOMATIC_REVIEW_ACTIONS = frozenset({"opened", "synchronize", "ready_for_review"})


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _repository_name(value: object) -> str | None:
    full_name = _mapping(value).get("full_name")
    return full_name if isinstance(full_name, str) and full_name.strip() else None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _label_names(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return [_mapping(label).get("name") for label in value]


def has_skip_agent_review_label(labels: Iterable[object]) -> bool:
    return any(isinstance(label, str) and label.strip().lower() == SKIP_AGENT_REVIEW_LABEL for label in labels)


@frozen
class PullRequestEvent:
    """The parts of an open, same-repository pull request delivery that ReviewHog acts on."""

    action: str
    installation_id: str
    repository: str
    github_repo_id: int | None
    pr_number: int
    author_login: str
    head_sha: str
    draft: bool = False
    skip_agent_review: bool = False

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "PullRequestEvent | None":
        action = payload.get("action")
        if not isinstance(action, str):
            return None
        pull_request = _mapping(payload.get("pull_request"))
        if pull_request.get("state") != "open" or pull_request.get("merged"):
            return None
        head = _mapping(pull_request.get("head"))
        base = _mapping(pull_request.get("base"))
        # The PR must come from a branch of the same repository, because a fork's head cannot be
        # trusted.
        names = [_repository_name(repo) for repo in (payload.get("repository"), head.get("repo"), base.get("repo"))]
        repository = names[0]
        if repository is None or any(name is None or name.lower() != repository.lower() for name in names):
            return None

        installation_id = _positive_int(_mapping(payload.get("installation")).get("id"))
        author_login = _text(_mapping(pull_request.get("user")).get("login"))
        pr_number = _positive_int(pull_request.get("number"))
        head_sha = _text(head.get("sha"))
        if installation_id is None or pr_number is None or author_login is None or head_sha is None:
            return None
        return cls(
            action=action,
            installation_id=str(installation_id),
            repository=repository,
            github_repo_id=_positive_int(_mapping(payload.get("repository")).get("id")),
            pr_number=pr_number,
            author_login=author_login.lower(),
            head_sha=head_sha,
            draft=pull_request.get("draft") is True,
            skip_agent_review=has_skip_agent_review_label(_label_names(pull_request.get("labels"))),
        )

    @property
    def ref(self) -> RepositoryRef:
        return RepositoryRef(
            installation_id=self.installation_id, github_repo_id=self.github_repo_id, full_name=self.repository
        )


def accept_pull_request_event(payload: Mapping[str, object]) -> None:
    event = PullRequestEvent.from_payload(payload)
    if event is None or event.action not in AUTOMATIC_REVIEW_ACTIONS:
        return
    if not OwnedRepositoryPrefilter.may_be_owned(event.ref):
        return
    # Keeps Celery off the registry import path.
    from products.review_hog.backend.tasks import process_authored_pr_event  # noqa: PLC0415

    process_authored_pr_event.delay(
        installation_id=event.installation_id,
        repository=event.repository,
        author_login=event.author_login,
        pr_number=event.pr_number,
        head_sha=event.head_sha,
        github_repo_id=event.github_repo_id,
        draft=event.draft,
        skip_agent_review=event.skip_agent_review,
    )
