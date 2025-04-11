from django.http import JsonResponse
from rest_framework.request import Request
from rest_framework import viewsets, status
from rest_framework.decorators import action
import json

# curl -X POST \
#  http://localhost:8000/api/payments/webhooks/ \
#  -H 'Content-Type: application/json' \
#  -d '{"test": "webhook_payload"}'


class StripeWebhookViewSet(viewsets.ViewSet):
    authentication_classes = []  # No auth for webhooks
    permission_classes = []  # No permissions for webhooks

    @action(methods=["post"], detail=False)
    def webhooks(self, request: Request):
        try:
            payload = json.loads(request.body)
            return JsonResponse({"status": "success", "payload": payload})
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "detail": "Invalid JSON"}, status=status.HTTP_400_BAD_REQUEST)
