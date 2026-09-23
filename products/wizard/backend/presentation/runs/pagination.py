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
        try:
            statuses = (
                tuple(WizardRunStatus(value) for value in raw_status.split(",")) if raw_status is not None else ()
            )
        except ValueError as error:
            raise ValidationError({"status": "Invalid run status."}) from error
        page = wizard_facade.list_runs(
            ListWizardRunsInput(
                team_id=team_id,
                offset=offset,
                limit=limit,
                statuses=statuses,
            )
        )
        self.request = request
        self.limit = limit
        self.offset = offset
        self.count = page.count
        return self.get_paginated_response(WizardRunSerializer(page.results, many=True).data)
