from typing import cast

from rest_framework import exceptions
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.cloud_utils import is_cloud, is_dev_mode
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User


class IsCloudOrDevDeployment(BasePermission):
    """
    Gates the legal-documents API to cloud (or a local DEBUG environment, so
    we can test the flow). Self-hosted production deployments don't have the
    PandaDoc / Slack credentials and the feature is a PostHog-owned workflow,
    not something customers run on their own infrastructure.
    """

    message = "Legal documents are only available on PostHog Cloud."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not (is_cloud() or is_dev_mode()):
            raise exceptions.NotFound("Not found.")
        return True


class IsOrganizationAdminOrOwner(BasePermission):
    """
    Allow access only to organization admins and owners (for every method,
    including reads). Mirrors the gate we apply to the Settings → Legal
    documents entry and the /legal scene in the frontend, so that non-admin
    members can't probe the API directly either.
    """

    message = "Your organization access level is insufficient."

    def has_permission(self, request: Request, view: "APIView") -> bool:
        organization = getattr(view, "organization", None)
        if organization is None:
            # Mixin hasn't resolved the org yet — defer. TeamAndOrgViewSetMixin
            # calls this after the URL kwarg has been parsed, so this branch is
            # effectively only hit on misconfigured routes.
            raise exceptions.NotFound("Organization not found.")
        try:
            membership = OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization)
        except OrganizationMembership.DoesNotExist:
            raise exceptions.NotFound("Organization not found.")
        return membership.level >= OrganizationMembership.Level.ADMIN
