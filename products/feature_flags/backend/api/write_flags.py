from typing import Any

from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin


class FeatureFlagWriteViewSetMixin(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # The legacy facade imports FeatureFlagSerializer from the consuming view module.
        from products.feature_flags.backend.api.feature_flag import apply_encrypted_payload_response_form
        from products.feature_flags.backend.facade.api import create_flag

        flag = create_flag(
            request.data,
            team=self.team,
            user=request.user,
            request=request,
            serializer_context=self.get_serializer_context(),
        )
        data = self.get_serializer(flag).data
        apply_encrypted_payload_response_form(request, data)
        headers = self.get_success_headers(data)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # The legacy facade imports FeatureFlagSerializer from the consuming view module.
        from products.feature_flags.backend.api.feature_flag import apply_encrypted_payload_response_form
        from products.feature_flags.backend.facade.api import update_flag

        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        flag = update_flag(
            instance,
            request.data,
            team=self.team,
            user=request.user,
            request=request,
            partial=partial,
            serializer_context=self.get_serializer_context(),
        )
        prefetched_objects = getattr(flag, "_prefetched_objects_cache", None)
        if prefetched_objects:
            prefetched_objects.clear()
        data = self.get_serializer(flag).data
        apply_encrypted_payload_response_form(request, data)
        return Response(data, status=status.HTTP_200_OK)
