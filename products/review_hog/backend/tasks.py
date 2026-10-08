from celery import shared_task

from products.review_hog.backend.automatic_reviews import AuthoredPRReview


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
def process_authored_pr_event(*, installation_id: str, author_login: str, pr_number: int, head_sha: str) -> None:
    AuthoredPRReview(
        installation_id=installation_id,
        author_login=author_login,
        pr_number=pr_number,
        head_sha=head_sha,
    ).start()
