from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import status
from rest_framework import viewsets
from products.messaging.backend.providers.mailjet import MailjetProvider


class MessageSetupViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    @action(methods=["POST"], detail=False)
    def email(self, request, **kwargs):
        """Create a new sender domain."""

        domain = request.data.get("domain")

        if not domain:
            return Response({"error": "Domain parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        mailjet = MailjetProvider()
        setup_result = mailjet.setup_email_domain(domain)
        return Response(setup_result)

    @action(methods=["POST"], detail=False)
    def email_verify(self, request, **kwargs):
        """Verify the sender domain has the correct SPF and DKIM records."""

        domain = request.data.get("domain")

        if not domain:
            return Response({"error": "Domain parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        mailjet = MailjetProvider()
        verification_result = mailjet.verify_email_domain(domain)
        return Response(verification_result)
