from __future__ import annotations

import json
import logging

from django.core.signing import BadSignature, SignatureExpired
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from products.streamlit_apps.backend.services.bridge import execute_bridge_query, validate_bridge_token

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class StreamlitBridgeView(View):
    http_method_names = ["post"]

    def post(self, request) -> JsonResponse:
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return JsonResponse({"error": "Missing or invalid Authorization header."}, status=401)

        token = auth_header[len("Bearer ") :]

        try:
            claims = validate_bridge_token(token)
        except SignatureExpired:
            return JsonResponse({"error": "Token expired."}, status=401)
        except BadSignature:
            return JsonResponse({"error": "Invalid token."}, status=401)

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            return JsonResponse({"error": "Missing or empty 'query' field."}, status=400)

        try:
            result = execute_bridge_query(query=query, team_id=claims.team_id)
            return JsonResponse(result)
        except Exception as err:
            logger.exception(
                "streamlit_bridge_query_failed",
                extra={"team_id": claims.team_id, "app_id": claims.app_id},
            )
            return JsonResponse({"error": str(err)}, status=400)
