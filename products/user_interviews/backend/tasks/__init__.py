# Re-exported so Celery autodiscovery registers the task when it imports `<app>.tasks`.
from products.user_interviews.backend.tasks.tasks import handle_vapi_webhook  # noqa: F401
