from django.conf import settings

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.cloud_utils import is_hobby


class ReplayVisionCloudOnly(BasePermission):
    """Refuse every replay vision request on a self-hosted install.

    A scan needs the AI gateway and the recording rasterizer worker, and self-hosted installs run
    neither, so a scanner created there would never produce an observation. The check matches
    `isHobby` in the frontend's preflightLogic, which hides the product on the same installs.
    """

    message = "Replay vision is only available on PostHog Cloud."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return not (is_hobby() and not settings.TEST)
