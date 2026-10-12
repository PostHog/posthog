from celery import shared_task

from products.review_hog.backend.automatic_reviews import AuthoredPRReview
from products.review_hog.backend.label_reviews import LabelReview


@shared_task(
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
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
) -> None:
    AuthoredPRReview(
        installation_id=installation_id,
        repository=repository,
        author_login=author_login,
        pr_number=pr_number,
        head_sha=head_sha,
        github_repo_id=github_repo_id,
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
)
def process_label_event(
    *,
    installation_id: str,
    repository: str,
    github_repo_id: int | None,
    pr_number: int,
    author_login: str,
    head_branch: str,
    labeler_login: str,
    labeled_by_bot: bool,
) -> None:
    LabelReview(
        installation_id=installation_id,
        repository=repository,
        github_repo_id=github_repo_id,
        pr_number=pr_number,
        author_login=author_login,
        head_branch=head_branch,
        labeler_login=labeler_login,
        labeled_by_bot=labeled_by_bot,
    ).start()
