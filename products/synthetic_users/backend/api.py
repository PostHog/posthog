from pydantic import BaseModel
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin

from .models import Study


class StudyInput(BaseModel):
    name: str
    audience_description: str
    research_goal: str
    target_url: str


def serialize_study(study: Study) -> dict:
    return {
        "id": str(study.id),
        "name": study.name,
        "audience_description": study.audience_description,
        "research_goal": study.research_goal,
        "target_url": study.target_url,
        "created_at": study.created_at.isoformat(),
    }


class SyntheticUsersViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "synthetic_users"

    @action(detail=False, methods=["GET"], required_scopes=["synthetic_users:read"])
    def get_studies(self, request: Request, *args, **kwargs) -> Response:
        studies = Study.objects.filter(team=self.team).order_by("-created_at")
        return Response(
            {"studies": [serialize_study(s) for s in studies]},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["GET"], required_scopes=["synthetic_users:read"])
    def get_study(self, request: Request, *args, **kwargs) -> Response:
        study_id = request.query_params.get("id")
        if not study_id:
            return Response({"error": "No study id provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            study = Study.objects.get(id=study_id, team=self.team)
        except Study.DoesNotExist:
            return Response({"error": "Study not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {"study": serialize_study(study)},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["POST"], required_scopes=["synthetic_users:write"])
    def create_study(self, request: Request, *args, **kwargs) -> Response:
        study_data = request.data.get("study", None)
        if study_data is None:
            return Response({"error": "No study data provided"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate input
        study_input = StudyInput(**study_data)

        # Create and save to DB
        study = Study.objects.create(
            team=self.team,
            name=study_input.name,
            audience_description=study_input.audience_description,
            research_goal=study_input.research_goal,
            target_url=study_input.target_url,
        )

        return Response(
            {"study": serialize_study(study)},
            status=status.HTTP_201_CREATED,
        )
