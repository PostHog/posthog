from celery import Task, shared_task

from products.review_hog.backend.automatic_reviews import AuthoredPRReview
from products.review_hog.backend.review_team_requests import ReviewTeamRequest
from products.review_hog.backend.stamphog_handoff import StamphogHandoff


@shared_task(
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    name="products.review_hog.backend.tasks.process_authored_pr_event",
)
def process_authored_pr_event(
    *,
    installation_id: str,
    author_login: str,
    pr_number: int,
    head_sha: str,
    # Messages queued before this argument existed came only from the one repository the handler
    # accepted then.
    repository: str = "PostHog/posthog",
    # Messages queued before this argument existed match the repository by name.
    github_repo_id: int | None = None,
    draft: bool = False,
    skip_agent_review: bool = False,
    action: str | None = None,
) -> None:
    AuthoredPRReview(
        installation_id=installation_id,
        repository=repository,
        author_login=author_login,
        pr_number=pr_number,
        head_sha=head_sha,
        github_repo_id=github_repo_id,
        draft=draft,
        skip_agent_review=skip_agent_review,
        action=action,
    ).start()


@shared_task(
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    name="products.review_hog.backend.tasks.process_stamphog_handoff",
)
def process_stamphog_handoff(
    *,
    repository: str,
    pr_number: int,
    head_sha: str,
    author_login: str,
    head_branch: str,
) -> None:
    StamphogHandoff(
        repository=repository,
        pr_number=pr_number,
        head_sha=head_sha,
        author_login=author_login,
        head_branch=head_branch,
    ).start()


@shared_task(
    bind=True,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    name="products.review_hog.backend.tasks.process_review_team_request",
)
def process_review_team_request(
    self: Task,
    *,
    installation_id: str,
    repository: str,
    github_repo_id: int | None,
    pr_number: int,
    requester_github_id: int,
    requester_login: str,
) -> None:
    ReviewTeamRequest(
        installation_id=installation_id,
        repository=repository,
        github_repo_id=github_repo_id,
        pr_number=pr_number,
        requester_github_id=requester_github_id,
        requester_login=requester_login,
    ).start(final_attempt=self.request.retries >= (self.max_retries or 0))
