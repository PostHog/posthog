"""Token-authed sandbox -> backend callback for SQLV2 runs (Journey 1 slice).

Mirrors PostHog Code's agent-proxy callback: a plain function view (no team
scoping, no session), authed by a Bearer token the run endpoint minted. Wired in
posthog/urls.py at internal/notebooks/runs/<run_id>/result/.
"""

import json

from django.core import signing
from django.http import JsonResponse

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema

from products.notebooks.backend.models import NotebookNodeRun
from products.notebooks.backend.sql_v2 import verify_callback_token
from products.notebooks.backend.sql_v2_serializers import NotebookSQLV2CallbackRequestSerializer

logger = structlog.get_logger(__name__)

# The envelope lands whole in a Postgres row. The kernel already caps streams, media, and
# preview cells well below this; anything bigger is a misbehaving (or hostile) sandbox, so
# reject rather than store. Sized above the kernel's worst case (~4 MB media + streams).
MAX_ENVELOPE_BYTES = 8_000_000


@extend_schema(
    tags=["notebooks"],
    request=NotebookSQLV2CallbackRequestSerializer,
    responses={
        200: OpenApiResponse(description="Result stored"),
        401: OpenApiResponse(description="Missing or invalid callback token"),
        403: OpenApiResponse(description="Token does not match the run"),
        404: OpenApiResponse(description="Run not found"),
    },
    summary="SQLV2 run result callback",
    description=(
        "Internal endpoint the notebook sandbox POSTs its result envelope to after a SQLV2 run. "
        "Authenticated with the signed callback token minted by the run endpoint (no session). "
        "Idempotent: re-delivery of the same run_id upserts the same row."
    ),
)
def notebook_sql_v2_callback(request, run_id: str) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return JsonResponse({"error": "Missing authorization bearer token"}, status=401)
    token = authorization[len("Bearer ") :].strip()
    if not token:
        return JsonResponse({"error": "Missing authorization bearer token"}, status=401)

    try:
        token_run_id, team_id = verify_callback_token(token)
    except signing.BadSignature:
        return JsonResponse({"error": "Invalid callback token"}, status=401)

    if token_run_id != run_id:
        return JsonResponse({"error": "Token does not match run"}, status=403)

    if len(request.body) > MAX_ENVELOPE_BYTES:
        logger.warning("sql_v2_callback_envelope_too_large", run_id=run_id, size=len(request.body))
        return JsonResponse({"error": "Envelope too large"}, status=400)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    serializer = NotebookSQLV2CallbackRequestSerializer(data=body)
    if not serializer.is_valid():
        return JsonResponse({"error": "Invalid request body", "detail": serializer.errors}, status=400)

    # Store the raw JSON envelope (JSON-native types) — the serializer's validated_data
    # would coerce result_id to a uuid.UUID, which the JSONField can't serialize.
    envelope = body["envelope"]

    try:
        run = NotebookNodeRun.objects.for_team(team_id).get(id=run_id)
    except NotebookNodeRun.DoesNotExist:
        return JsonResponse({"error": "Run not found"}, status=404)

    status_by_envelope = {
        "ok": NotebookNodeRun.Status.DONE,
        "interrupted": NotebookNodeRun.Status.INTERRUPTED,
    }
    run.status = status_by_envelope.get(envelope.get("status"), NotebookNodeRun.Status.FAILED)
    run.envelope = envelope
    run.result_id = envelope.get("result_id")
    run.error = envelope.get("error")
    run.save(update_fields=["status", "envelope", "result_id", "error", "updated_at"])

    return JsonResponse({"ok": True})
