"""The heartbeat a sandbox sends while a long cell executes.

Mounted by the product's routes module at api/notebooks/sandbox/heartbeat/. The sandbox calls it
with the signed data-plane token from its run, not a session.
"""

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from drf_spectacular.utils import OpenApiResponse, extend_schema

from products.notebooks.backend.facade.sql_v2 import record_sandbox_heartbeat


@csrf_exempt
@extend_schema(
    tags=["notebooks"],
    request=None,
    responses={
        204: OpenApiResponse(description="Progress recorded"),
        401: OpenApiResponse(description="Missing or invalid data-plane token"),
    },
    summary="SQLV2 data-plane heartbeat",
    description=(
        "Internal endpoint the notebook sandbox POSTs to while a cell executes. Authenticated with "
        "the signed data-plane token minted at run dispatch. Resets the run's watchdog clock and "
        "renews its concurrency slots, so a long cell is not failed while it works."
    ),
)
def notebook_sql_v2_data_plane_heartbeat(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if not token:
        return JsonResponse({"error": "Missing authorization bearer token"}, status=401)
    if not record_sandbox_heartbeat(token):
        return JsonResponse({"error": "Invalid data-plane token"}, status=401)
    return HttpResponse(status=204)
