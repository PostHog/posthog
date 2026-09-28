from django.utils import timezone
from django.utils.dateparse import parse_datetime

from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import ListWizardRunsInput
from products.wizard.backend.facade.enums import WizardRunStatus
from products.wizard.backend.presentation.runs.serializers import WizardRunSerializer


class WizardRunPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 100

    def paginate_runs(self, request: Request, *, team_id: int) -> Response:
        limit = self.get_limit(request)
        assert limit is not None
        offset = self.get_offset(request)
        raw_status = request.query_params.get("status")
        raw_created_after = request.query_params.get("created_after")
        try:
            statuses = (
                tuple(WizardRunStatus(value) for value in raw_status.split(",")) if raw_status is not None else ()
            )
        except ValueError as error:
            raise ValidationError({"status": "Invalid run status."}) from error
        created_after = parse_datetime(raw_created_after) if raw_created_after is not None else None
        if raw_created_after is not None and (created_after is None or not timezone.is_aware(created_after)):
            raise ValidationError({"created_after": "Use an ISO 8601 timestamp with a timezone."})
        page = wizard_facade.list_runs(
            ListWizardRunsInput(
                team_id=team_id,
                offset=offset,
                limit=limit,
                statuses=statuses,
                created_after=created_after,
            )
        )
        self.request = request
        self.limit = limit
        self.offset = offset
        self.count = page.count
        return self.get_paginated_response(WizardRunSerializer(page.results, many=True).data)
