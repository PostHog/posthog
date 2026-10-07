from celery import shared_task

from products.review_hog.backend.automatic_reviews import AuthoredPRReview, skip_event_without_state


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
    repository: str | None = None,
    action: str | None = None,
    base_ref: str | None = None,
    draft: bool | None = None,
    labels: list[str] | None = None,
) -> None:
    if repository is None or action is None or base_ref is None or draft is None or labels is None:
        skip_event_without_state(pr_number)
        return
    AuthoredPRReview(
        installation_id=installation_id,
        repository=repository,
        author_login=author_login,
        pr_number=pr_number,
        head_sha=head_sha,
        action=action,
        base_ref=base_ref,
        draft=draft,
        labels=tuple(labels),
    ).start()
