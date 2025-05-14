from rest_framework import viewsets
from rest_framework.parsers import MultiPartParser

from posthog.api.routing import TeamAndOrgViewSetMixin
from .models import UserInterview
from .serializers import UserInterviewSerializer


class UserInterviewViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "user_interview"
    queryset = UserInterview.objects.all().order_by("-created_at")
    serializer_class = UserInterviewSerializer
    parser_classes = [MultiPartParser]
