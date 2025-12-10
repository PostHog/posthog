from uuid import uuid4

from django.conf import settings

import structlog
import posthoganalytics
from posthoganalytics.ai.openai import OpenAI
from pydantic import BaseModel
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import PydanticModelMixin
from posthog.api.routing import TeamAndOrgViewSetMixin

from .models import Round, Session, Study

logger = structlog.get_logger(__name__)


class StudyInput(BaseModel):
    name: str
    audience_description: str
    research_goal: str
    target_url: str


class RoundInput(BaseModel):
    study_id: str
    session_count: int
    notes: str | None = None


class GenerateSessionsInput(BaseModel):
    round_id: str


class RegenerateSessionInput(BaseModel):
    session_id: str


class PersonaOutput(BaseModel):
    name: str
    archetype: str
    background: str
    traits: list[str]
    plan: str


def serialize_session(session: Session) -> dict:
    return {
        "id": str(session.id),
        "round_id": str(session.round_id),
        "name": session.name,
        "archetype": session.archetype,
        "background": session.background,
        "traits": session.traits,
        "plan": session.plan,
        "status": session.status,
        "session_replay_url": session.session_replay_url,
        "thought_action_log": session.thought_action_log,
        "experience_writeup": session.experience_writeup,
        "key_insights": session.key_insights,
        "sentiment": session.sentiment,
        "created_at": session.created_at.isoformat(),
    }


def serialize_round(round: Round, include_sessions: bool = False) -> dict:
    data = {
        "id": str(round.id),
        "study_id": str(round.study_id),
        "round_number": round.round_number,
        "session_count": round.session_count,
        "notes": round.notes,
        "status": round.status,
        "summary": round.summary,
        "created_at": round.created_at.isoformat(),
    }
    if include_sessions:
        data["sessions"] = [serialize_session(s) for s in round.sessions.all()]
    return data


def serialize_study(study: Study, include_rounds: bool = False) -> dict:
    data = {
        "id": str(study.id),
        "name": study.name,
        "audience_description": study.audience_description,
        "research_goal": study.research_goal,
        "target_url": study.target_url,
        "created_at": study.created_at.isoformat(),
    }
    if include_rounds:
        data["rounds"] = [serialize_round(r, include_sessions=True) for r in study.rounds.all()]
    return data


class SyntheticUsersViewSet(TeamAndOrgViewSetMixin, PydanticModelMixin, viewsets.ViewSet):
    scope_object = "synthetic_users"

    # ==================
    # Study endpoints
    # ==================

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
            study = Study.objects.prefetch_related("rounds__sessions").get(id=study_id, team=self.team)
        except Study.DoesNotExist:
            return Response({"error": "Study not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {"study": serialize_study(study, include_rounds=True)},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["POST"], required_scopes=["synthetic_users:write"])
    def create_study(self, request: Request, *args, **kwargs) -> Response:
        study_data = request.data.get("study", None)
        if study_data is None:
            return Response({"error": "No study data provided"}, status=status.HTTP_400_BAD_REQUEST)

        study_input = StudyInput(**study_data)

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

    # ==================
    # Round endpoints
    # ==================

    @action(detail=False, methods=["POST"], required_scopes=["synthetic_users:write"])
    def create_round(self, request: Request, *args, **kwargs) -> Response:
        round_data = request.data.get("round", None)
        if round_data is None:
            return Response({"error": "No round data provided"}, status=status.HTTP_400_BAD_REQUEST)

        round_input = RoundInput(**round_data)

        try:
            study = Study.objects.get(id=round_input.study_id, team=self.team)
        except Study.DoesNotExist:
            return Response({"error": "Study not found"}, status=status.HTTP_404_NOT_FOUND)

        # Get the next round number
        last_round = study.rounds.order_by("-round_number").first()
        next_round_number = (last_round.round_number + 1) if last_round else 1

        round = Round.objects.create(
            team=self.team,
            study=study,
            round_number=next_round_number,
            session_count=round_input.session_count,
            notes=round_input.notes,
            status=Round.Status.DRAFT,
        )

        return Response(
            {"round": serialize_round(round)},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["POST"], required_scopes=["synthetic_users:write"])
    def generate_sessions(self, request: Request, *args, **kwargs) -> Response:
        """Generate personas for all sessions in a round using OpenAI."""
        input_data = request.data.get("round_id")
        if not input_data:
            return Response({"error": "No round_id provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            round = Round.objects.prefetch_related("sessions").get(id=input_data, team=self.team)
        except Round.DoesNotExist:
            return Response({"error": "Round not found"}, status=status.HTTP_404_NOT_FOUND)

        if round.status != Round.Status.DRAFT:
            return Response(
                {"error": f"Round must be in draft status to generate sessions (current: {round.status})"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Delete any existing sessions (in case of retry)
        round.sessions.all().delete()

        # Update round status to generating
        round.status = Round.Status.GENERATING
        round.save(update_fields=["status"])

        study = round.study
        logger.info("generating_sessions", round_id=str(round.id), session_count=round.session_count)

        try:
            generated_personas: list[dict] = []
            for i in range(round.session_count):
                persona = self._generate_persona_sync(study, self.request.user, i, existing_personas=generated_personas)
                generated_personas.append(persona)
                Session.objects.create(
                    team=self.team,
                    round=round,
                    name=persona["name"],
                    archetype=persona["archetype"],
                    background=persona["background"],
                    traits=persona["traits"],
                    plan=persona["plan"],
                    status=Session.Status.PENDING,
                )

            # Update round status to ready
            round.status = Round.Status.READY
            round.save(update_fields=["status"])

            logger.info("sessions_generated", round_id=str(round.id), session_count=len(generated_personas))
            return Response(
                {"round": serialize_round(round, include_sessions=True)},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.exception("session_generation_failed", round_id=str(round.id), error=str(e))
            round.status = Round.Status.FAILED
            round.save(update_fields=["status"])
            return Response(
                {"error": f"Failed to generate sessions: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _generate_persona_sync(
        self, study: Study, user, index: int, existing_personas: list[dict] | None = None
    ) -> dict:
        """Generate a single persona using OpenAI."""
        existing_context = ""
        if existing_personas:
            existing_names = ", ".join(p["name"] for p in existing_personas)
            existing_archetypes = ", ".join(p["archetype"] for p in existing_personas)
            existing_context = f"""
Already generated personas (avoid duplicating these):
- Names used: {existing_names}
- Archetypes used: {existing_archetypes}
"""

        client = OpenAI(
            posthog_client=posthoganalytics.default_client,
            base_url=settings.OPENAI_BASE_URL,
        )

        response = client.responses.parse(
            model="gpt-4.1-mini",
            posthog_distinct_id=user.distinct_id,
            posthog_trace_id=str(uuid4()),
            input=[
                {
                    "role": "system",
                    "content": """You are an expert UX researcher creating synthetic user personas for website testing.
Generate a realistic, diverse persona that would naturally be part of the target audience.
The persona should have:
- A believable full name
- A specific archetype (e.g., "Skeptical Developer", "First-time Founder", "Enterprise Buyer")
- Background that explains their context and how they fit the audience
- 3-5 personality traits that will influence how they browse
- A brief plan for how they'll navigate the site given the research goal""",
                },
                {
                    "role": "user",
                    "content": f"""Generate persona #{index + 1} for this study:

Target Audience: {study.audience_description}
Research Goal: {study.research_goal}
Target URL: {study.target_url}
{existing_context}

Generate a unique persona that fits this audience and would provide useful testing insights.""",
                },
            ],
            text_format=PersonaOutput,
        )

        return response.output_parsed.model_dump()

    @action(detail=False, methods=["POST"], required_scopes=["synthetic_users:write"])
    def regenerate_session(self, request: Request, *args, **kwargs) -> Response:
        """Regenerate a single session's persona."""
        session_id = request.data.get("session_id")
        if not session_id:
            return Response({"error": "No session_id provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = Session.objects.select_related("round", "round__study").get(id=session_id, team=self.team)
        except Session.DoesNotExist:
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

        if session.round.status not in [Round.Status.DRAFT, Round.Status.READY]:
            return Response(
                {"error": "Can only regenerate sessions in draft or ready rounds"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get session index for variety
        session_index = list(session.round.sessions.order_by("created_at").values_list("id", flat=True)).index(
            session.id
        )

        logger.info("regenerating_session", session_id=str(session.id))

        try:
            persona = self._generate_persona_sync(
                session.round.study, self.request.user, session_index + 100
            )  # offset for variety
            session.name = persona["name"]
            session.archetype = persona["archetype"]
            session.background = persona["background"]
            session.traits = persona["traits"]
            session.plan = persona["plan"]
            session.save(update_fields=["name", "archetype", "background", "traits", "plan"])

            return Response(
                {"session": serialize_session(session)},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.exception("session_regeneration_failed", session_id=str(session.id), error=str(e))
            return Response(
                {"error": f"Failed to regenerate session: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["POST"], required_scopes=["synthetic_users:write"])
    def start_round(self, request: Request, *args, **kwargs) -> Response:
        """Start executing a round - begins navigation for all sessions."""
        round_id = request.data.get("round_id")
        if not round_id:
            return Response({"error": "No round_id provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            round = Round.objects.prefetch_related("sessions").get(id=round_id, team=self.team)
        except Round.DoesNotExist:
            return Response({"error": "Round not found"}, status=status.HTTP_404_NOT_FOUND)

        if round.status != Round.Status.READY:
            return Response(
                {"error": f"Round must be in ready status to start (current: {round.status})"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if round.sessions.count() == 0:
            return Response(
                {"error": "Round has no sessions. Generate sessions first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info("starting_round", round_id=str(round.id))

        # Update round status to running
        round.status = Round.Status.RUNNING
        round.save(update_fields=["status"])

        # TODO: Kick off actual navigation tasks (Celery jobs, etc.)
        # For now, just update session statuses to navigating
        round.sessions.update(status=Session.Status.NAVIGATING)

        return Response(
            {"round": serialize_round(round, include_sessions=True)},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["POST"], required_scopes=["synthetic_users:write"])
    def start_session(self, request: Request, *args, **kwargs) -> Response:
        """Start executing a single session."""
        session_id = request.data.get("session_id")
        if not session_id:
            return Response({"error": "No session_id provided"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = Session.objects.select_related("round").get(id=session_id, team=self.team)
        except Session.DoesNotExist:
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

        round = session.round
        if round.status not in [Round.Status.READY, Round.Status.RUNNING]:
            return Response(
                {"error": f"Round must be in ready or running status to start sessions (current: {round.status})"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if session.status != Session.Status.PENDING:
            return Response(
                {"error": f"Session must be in pending status to start (current: {session.status})"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info("starting_session", session_id=str(session.id))

        # If round is ready, transition it to running
        if round.status == Round.Status.READY:
            round.status = Round.Status.RUNNING
            round.save(update_fields=["status"])

        # Update session status to navigating
        session.status = Session.Status.NAVIGATING
        session.save(update_fields=["status"])

        # TODO: Kick off actual navigation task (Celery job, etc.)

        return Response(
            {"session": serialize_session(session)},
            status=status.HTTP_200_OK,
        )
