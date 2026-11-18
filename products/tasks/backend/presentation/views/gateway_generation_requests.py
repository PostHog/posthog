import re
import hmac
import json
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from posthog.models.project_secret_api_key import find_project_secret_api_key

from products.tasks.backend.facade.gateway import accept_generation_request

_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,255}\Z")


def gateway_generation_request(request: HttpRequest, team_id: int, run_id: str, request_id: str) -> HttpResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    expected_token = settings.AI_GATEWAY_INTERNAL_TOKEN or ""
    authorization = request.headers.get("Authorization", "")
    prefix = "Bearer "
    token = authorization[len(prefix) :] if authorization.startswith(prefix) else ""
    if not expected_token or not hmac.compare_digest(token.encode(), expected_token.encode()):
        return JsonResponse({"error": "Invalid service credential"}, status=401)

    wallet_header = request.headers.get("X-PostHog-Gateway-Team-Id", "")
    try:
        wallet_team_id = int(wallet_header)
    except ValueError:
        return JsonResponse({"error": "Invalid gateway team ID"}, status=400)
    if wallet_team_id <= 0:
        return JsonResponse({"error": "Invalid gateway team ID"}, status=400)

    if wallet_team_id != team_id:
        mint_key = settings.SANDBOX_AI_GATEWAY_MINT_KEY
        mint_key_record = find_project_secret_api_key(mint_key) if mint_key else None
        if wallet_team_id != (mint_key_record.team_id if mint_key_record else None):
            return JsonResponse({"error": "Gateway team cannot fund this task run"}, status=403)

    try:
        parsed_run_id = UUID(run_id)
    except ValueError:
        return JsonResponse({"error": "Invalid task run ID"}, status=400)
    if str(parsed_run_id) != run_id or _REQUEST_ID.fullmatch(request_id) is None:
        return JsonResponse({"error": "Invalid generation request ID"}, status=400)

    if request.body.strip():
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid request body"}, status=400)
        if body != {}:
            return JsonResponse({"error": "Invalid request body"}, status=400)

    if not accept_generation_request(team_id=team_id, run_id=parsed_run_id, request_id=request_id):
        return JsonResponse({"error": "Task run not found"}, status=404)
    return HttpResponse(status=204)
