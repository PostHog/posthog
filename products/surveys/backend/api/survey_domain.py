import asyncio
from typing import Any

from django.conf import settings
from django.core.cache import cache

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.proxy_record import generate_target_cname
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature
from posthog.models import ProxyRecord
from posthog.temporal.common.client import sync_connect
from posthog.temporal.proxy_service import CreateManagedProxyInputs, DeleteManagedProxyInputs

from products.surveys.backend.models import SurveyDomain


class SurveyDomainSerializer(serializers.ModelSerializer):
    status = serializers.CharField(source="proxy_record.status", read_only=True, default=None)
    target_cname = serializers.CharField(source="proxy_record.target_cname", read_only=True, default=None)

    class Meta:
        model = SurveyDomain
        fields = (
            "id",
            "domain",
            "redirect_url",
            "status",
            "target_cname",
            "created_at",
            "updated_at",
            "created_by",
        )
        read_only_fields = ("id", "created_at", "updated_at", "created_by")


class SurveyDomainViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "survey"
    serializer_class = SurveyDomainSerializer

    def _get_survey_domain(self) -> SurveyDomain | None:
        try:
            return SurveyDomain.objects.select_related("proxy_record").get(team=self.team)
        except SurveyDomain.DoesNotExist:
            return None

    def _invalidate_cache(self, domain: str) -> None:
        cache.delete(f"survey_domain:{domain}")

    def list(self, request, **kwargs: Any) -> Response:
        survey_domain = self._get_survey_domain()
        if survey_domain is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(survey_domain)
        return Response(serializer.data)

    def create(self, request, **kwargs: Any) -> Response:
        if not self.organization.is_feature_available(AvailableFeature.WHITE_LABELLING):
            return Response(
                {"detail": "This feature requires the white labelling add-on."},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        existing = self._get_survey_domain()
        if existing is not None:
            return Response(
                {"detail": "A survey domain already exists for this team. Delete it first to configure a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        domain = request.data.get("domain", "").strip().lower()
        if not domain:
            return Response(
                {"detail": "The domain field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if SurveyDomain.objects.filter(domain=domain).exists():
            return Response(
                {"detail": "This domain is already in use."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if ProxyRecord.objects.filter(domain=domain).exists():
            return Response(
                {"detail": "This domain is already configured as a reverse proxy."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        proxy_record = ProxyRecord.objects.create(
            organization_id=self.organization.id,
            created_by=request.user,
            domain=domain,
            target_cname=generate_target_cname(self.organization.id, domain),
        )

        survey_domain = SurveyDomain.objects.create(
            team=self.team,
            domain=domain,
            redirect_url=request.data.get("redirect_url", ""),
            proxy_record=proxy_record,
            created_by=request.user,
        )

        temporal = sync_connect()
        inputs = CreateManagedProxyInputs(
            organization_id=proxy_record.organization_id,
            proxy_record_id=proxy_record.id,
            domain=proxy_record.domain,
            target_cname=proxy_record.target_cname,
        )
        asyncio.run(
            temporal.start_workflow(
                "create-proxy",
                inputs,
                id=f"proxy-create-{inputs.proxy_record_id}",
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            )
        )

        serializer = self.get_serializer(survey_domain)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["patch"], url_path="update", url_name="update")
    def update_domain(self, request, **kwargs: Any) -> Response:
        survey_domain = self._get_survey_domain()
        if survey_domain is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if "redirect_url" in request.data:
            survey_domain.redirect_url = request.data["redirect_url"]
            survey_domain.save(update_fields=["redirect_url", "updated_at"])

        self._invalidate_cache(survey_domain.domain)
        serializer = self.get_serializer(survey_domain)
        return Response(serializer.data)

    @action(detail=False, methods=["delete"], url_path="delete", url_name="delete")
    def delete_domain(self, request, **kwargs: Any) -> Response:
        survey_domain = self._get_survey_domain()
        if survey_domain is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        domain = survey_domain.domain
        proxy_record = survey_domain.proxy_record

        if proxy_record:
            if proxy_record.status in (
                ProxyRecord.Status.WAITING,
                ProxyRecord.Status.ERRORING,
                ProxyRecord.Status.TIMED_OUT,
            ):
                survey_domain.delete()
                proxy_record.delete()
            else:
                survey_domain.delete()
                temporal = sync_connect()
                inputs = DeleteManagedProxyInputs(
                    organization_id=proxy_record.organization_id,
                    proxy_record_id=proxy_record.id,
                    domain=proxy_record.domain,
                    target_cname=proxy_record.target_cname,
                )
                asyncio.run(
                    temporal.start_workflow(
                        "delete-proxy",
                        inputs,
                        id=f"proxy-delete-{inputs.proxy_record_id}",
                        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                    )
                )
                proxy_record.status = ProxyRecord.Status.DELETING
                proxy_record.save()
        else:
            survey_domain.delete()

        self._invalidate_cache(domain)
        return Response({"success": True}, status=status.HTTP_200_OK)
