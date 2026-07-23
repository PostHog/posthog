"""Cross-region workspace-claims evaluation.

Shared by the legacy ``/slack/workspace/claims/`` route and the generic
``/chat/<provider>/workspace/claims/`` route; lives in services so both the product's
``api`` module and its ``views`` package can import it without a cycle.
"""

import json

from django.http import HttpRequest, HttpResponse, JsonResponse

import structlog

from posthog.models.integration import (
    SLACK_INTEGRATION_KINDS,
    Integration,
    SlackIntegrationError,
    validate_slack_request,
)

from products.slack_app.backend.services.region_auth import (
    REGION_SIGNATURE_HEADER,
    RegionAuthError,
    region_claims_secret,
    validate_region_request,
)

logger = structlog.get_logger(__name__)

# Integration.kind values each chat provider may claim a workspace for. Adding a provider
# means adding its kinds here and its secret to ``region_claims_secret``.
_PROVIDER_CLAIM_KINDS: dict[str, frozenset[str]] = {"slack": frozenset(SLACK_INTEGRATION_KINDS)}


def evaluate_workspace_claims(request: HttpRequest, provider: str) -> HttpResponse:
    """Cross-region probe: does this region hold an Integration row for the given workspace?

    Authenticated with the neutral region signature headers. The Slack provider also
    accepts the legacy Slack webhook headers so the two Cloud regions can upgrade
    independently. The signed body covers the workspace id + kinds, so a captured
    signature cannot be replayed against a different workspace.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    valid_kinds = _PROVIDER_CLAIM_KINDS.get(provider)
    if valid_kinds is None:
        return HttpResponse(status=404)

    try:
        secret = region_claims_secret(provider)
        if request.headers.get(REGION_SIGNATURE_HEADER):
            validate_region_request(request, secret)
        elif provider == "slack":
            validate_slack_request(request, secret)
        else:
            raise RegionAuthError("Missing region signature")
    except (RegionAuthError, SlackIntegrationError) as e:
        logger.warning("slack_app_workspace_claims_invalid_request", provider=provider, error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    workspace_id = data.get("workspace_id") or data.get("slack_team_id")
    kinds = data.get("kinds")
    if not isinstance(workspace_id, str) or not workspace_id:
        return HttpResponse("Missing workspace_id", status=400)
    if not isinstance(kinds, list) or not kinds:
        return HttpResponse("Missing kinds", status=400)
    filtered = [k for k in kinds if isinstance(k, str) and k in valid_kinds]
    if not filtered:
        return HttpResponse("No valid kinds", status=400)

    claimed = Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
        kind__in=filtered,
        integration_id=workspace_id,
    ).exists()
    return JsonResponse({"claimed": claimed})
