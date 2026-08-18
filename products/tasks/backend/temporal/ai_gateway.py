from django.conf import settings

import requests
import structlog

from posthog.models.oauth import find_oauth_access_token
from posthog.storage.gateway_credential_cache import project_gateway_credential
from posthog.temporal.oauth import TOKEN_EXPIRATION_SECONDS

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.oauth import is_interactive_signals_task

logger = structlog.get_logger(__name__)

# Pinned as the token's `product` attribution node, so the Go gateway keys budgets on it no
# matter what the sandbox declares. This is the same non-evadable budget boundary the Python
# gateway derives from the `interactive_run:read` token scope; per-stage attribution
# (`ai_stage`) still travels in the properties blob.
SIGNALS_INTERACTIVE_AI_PRODUCT = "signals_interactive"

_MINT_TIMEOUT_SECONDS = 10


def mint_signals_scoped_token(task: Task, access_token: str) -> str | None:
    """A capped Go-gateway scoped token (phe_) for an interactive Signals run, or None.

    The token carries the per-run spend cap and pins `product`/`user`/`obo` at mint, so the
    gateway enforces them regardless of what the sandbox sends. Minting is enabled by
    `AI_GATEWAY_MINT_URL`; any failure returns None with a warning, so a gateway outage
    degrades the run to its OAuth token (uncapped on the Go path) instead of failing it.
    """
    if not settings.AI_GATEWAY_MINT_URL or not is_interactive_signals_task(task):
        return None

    token_row = find_oauth_access_token(access_token)
    if token_row is None or token_row.user_id is None:
        logger.warning("signals_scoped_token_mint_missing_oauth_row", task_id=str(task.id))
        return None

    mint_credential = settings.AI_GATEWAY_MINT_CREDENTIAL
    if not mint_credential:
        # Minting with the run's own OAuth token: the gateway authenticates it from the
        # projected credential blob, which normally lands via a post-commit Celery task, so
        # project it synchronously to keep this mint from racing the projection.
        project_gateway_credential(token_row)
        mint_credential = access_token

    payload = {
        "cap_usd": settings.TASKS_SIGNALS_INTERACTIVE_COST_CAP_USD,
        "ttl_seconds": TOKEN_EXPIRATION_SECONDS,
        "product": SIGNALS_INTERACTIVE_AI_PRODUCT,
        "user": str(token_row.user_id),
        "obo": str(task.team_id),
    }
    try:
        response = requests.post(
            f"{settings.AI_GATEWAY_MINT_URL.rstrip('/')}/v1/tokens",
            json=payload,
            headers={"Authorization": f"Bearer {mint_credential}"},
            timeout=_MINT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        token = response.json().get("token")
    except Exception as e:
        logger.warning("signals_scoped_token_mint_failed", task_id=str(task.id), error=str(e))
        return None

    if not isinstance(token, str) or not token:
        logger.warning("signals_scoped_token_mint_bad_response", task_id=str(task.id))
        return None
    return token
