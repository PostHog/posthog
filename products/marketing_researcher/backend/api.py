from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet
from rest_framework import serializers
from rest_framework.permissions import AllowAny

from .service import marketing_researcher_service


class MarketingResearchSerializer(serializers.Serializer):
    websiteurl = serializers.URLField(help_text="Website URL to find competitors for")
    summaryText = serializers.CharField(max_length=2000, help_text="Summary text describing what the company does")


class MarketingResearchViewSet(ViewSet):
    authentication_classes = []
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"])
    def find_competitors(self, request):
        if not marketing_researcher_service.is_available:
            return Response(
                {
                    "error": "Marketing Researcher service is not available. Please configure EXA_API_KEY in environment variables."
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = MarketingResearchSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validated_data = serializer.validated_data
            website_url = validated_data["websiteurl"]
            summary_text = validated_data["summaryText"]

            if not website_url or not summary_text:
                return Response(
                    {"error": "Website URL and summary text are required"}, status=status.HTTP_400_BAD_REQUEST
                )

            result = marketing_researcher_service.find_competitors(website_url, summary_text)

            return Response({"results": result})

        except Exception as e:
            return Response({"error": f"Failed to perform search | {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
