from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.utils.timezone import now

import requests
import posthoganalytics
from rest_framework import mixins, request, serializers, viewsets
from rest_framework.response import Response

from posthog.cloud_utils import is_cloud
from posthog.event_usage import groups
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.enterprise.backend.models.license import License, LicenseError


class LicenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = License
        fields = [
            "id",
            "plan",
            "key",
            "valid_until",
            "created_at",
        ]
        read_only_fields = ["plan", "valid_until"]
        write_only_fields = ["key"]

    def validate(self, data):
        validation = requests.post("https://license.posthog.com/licenses/activate", data={"key": data["key"]})
        resp = validation.json()
        user = self.context["request"].user
        if not validation.ok:
            posthoganalytics.capture(
                "license key activation failure",
                distinct_id=user.distinct_id,
                properties={"error": validation.content},
                groups=groups(user.current_organization, user.current_team),
            )
            raise LicenseError(resp["code"], resp["detail"])

        posthoganalytics.capture(
            "license key activation success",
            distinct_id=user.distinct_id,
            properties={},
            groups=groups(user.current_organization, user.current_team),
        )
        data["valid_until"] = resp["valid_until"]
        data["plan"] = resp["plan"]
        return data


class LicenseViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = License.objects.all()
    serializer_class = LicenseSerializer

    def get_queryset(self) -> QuerySet:
        if is_cloud():
            return License.objects.none()

        return super().get_queryset()

    def destroy(self, request: request.Request, pk=None, **kwargs) -> Response:
        license = get_object_or_404(License, pk=pk)
        validation = requests.post("https://license.posthog.com/licenses/deactivate", data={"key": license.key})
        validation.raise_for_status()

        has_another_valid_license = License.objects.filter(valid_until__gte=now()).exclude(pk=pk).exists()
        if not has_another_valid_license:
            teams = Team.objects.exclude(is_demo=True).order_by("pk")[1:]
            for team in teams:
                team.delete()

            #  delete any organization where we've deleted all teams
            # there is no way in the interface to create multiple organizations so we won't bother informing people that this is happening
            for organization in Organization.objects.all():
                if organization.teams.count() == 0:
                    organization.delete()

        license.delete()

        return Response({"ok": True})
