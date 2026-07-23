"""Generic cross-region workspace-claims endpoint, parameterized by chat provider."""

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from products.slack_app.backend.services.region_claims import evaluate_workspace_claims


@csrf_exempt
def chat_workspace_claims_view(request: HttpRequest, provider: str) -> HttpResponse:
    return evaluate_workspace_claims(request, provider)
