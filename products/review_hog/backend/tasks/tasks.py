from celery import shared_task

from products.review_hog.backend.automatic_reviews import AuthoredPRReview
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
