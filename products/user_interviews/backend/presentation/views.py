import re
import json
from functools import cache, cached_property
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files import File
from django.db import models, transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.text import slugify

import structlog
import django_filters
import posthoganalytics
import posthoganalytics.ai.openai
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from posthoganalytics.ai.openai import OpenAI
from rest_framework import filters, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework_csv import renderers as csvrenderers

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import generate_embedding
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.email import EmailMessage, is_email_available
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rate_limit import UserInterviewInviteThrottle
from posthog.security.spreadsheet_safety import sanitize_formula_injection
from posthog.utils import absolute_uri

from ..facade.api import derive_auto_classifications, parse_interviewee_identifier
from ..facade.enums import SEARCH_DOCUMENT_TYPES
from ..invite_email import (
    build_invite_email_context,
    resolve_invite_preview,
    validate_invite_message,
    validate_invite_subject,
)
from ..models import (
    EmailWithDisplayNameValidator,
    IntervieweeContext,
    UserInterview,
    UserInterviewClassification,
    UserInterviewTopic,
)

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from elevenlabs import ElevenLabs


@cache
def _get_elevenlabs_client() -> "ElevenLabs":
    # Deferred import + cached instance: the elevenlabs SDK is slow to import and
    # only the audio transcription path needs it, not every process that loads this module.
    from elevenlabs import ElevenLabs

    return ElevenLabs()


class _InterviewLinksCSVRenderer(csvrenderers.CSVRenderer):
    """Lock the CSV column order for interview-links exports."""

    header = ["interviewee_identifier", "interviewee_email", "user_name", "interview_url"]


class UserInterviewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    audio = serializers.FileField(write_only=True)
    classifications = serializers.ListField(
        child=serializers.ChoiceField(choices=UserInterviewClassification.choices),
        required=False,
        help_text=(
            "Searchable classifications on the response. `abandoned` is auto-derived from the transcript when "
            "the interview is recorded; `off-topic` is set manually. Sending `classifications` on an update "
            "replaces the whole list — pass the full desired set, not a delta."
        ),
    )

    class Meta:
        model = UserInterview
        fields = (
            "id",
            "created_by",
            "created_at",
            "interviewee_emails",
            "interviewee_identifier",
            "topic",
            "transcript",
            "summary",
            "classifications",
            "audio",
        )
        read_only_fields = ("id", "created_by", "created_at", "interviewee_identifier", "topic", "transcript")

    def create(self, validated_data: dict) -> UserInterview:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        audio = validated_data.pop("audio")
        validated_data["transcript"] = self._transcribe_audio(audio, validated_data["interviewee_emails"])
        validated_data["summary"] = self._summarize_transcript(validated_data["transcript"])
        validated_data["classifications"] = derive_auto_classifications(validated_data["transcript"])
        return super().create(validated_data)

    def _transcribe_audio(self, audio: File, interviewee_emails: list[str]) -> str:
        transcript = _get_elevenlabs_client().speech_to_text.convert(
            model_id="scribe_v1",
            file=audio,
            num_speakers=10,  # Maximum number of speakers, not expected one
            diarize=True,
            tag_audio_events=False,
            additional_formats=json.dumps(  # type: ignore
                [
                    {
                        "format": "txt",
                        "include_timestamps": False,
                        "segment_on_silence_longer_than_s": 10,
                    }
                ]
            ),
        )

        transcript_text = transcript.additional_formats[0].content.strip()  # type: ignore

        speaker_mapping = self._attempt_to_map_speaker_names(transcript_text, interviewee_emails)
        if speaker_mapping:
            for speaker_marker, speaker_name in speaker_mapping.items():
                transcript_text = transcript_text.replace(speaker_marker, speaker_name)
            formatted_transcript_text = re.sub(r"\[(.+)\]", "#### \\1", transcript_text)
        else:
            # Always fall back to formatting speaker numbers if we can't map names
            formatted_transcript_text = re.sub(r"\[speaker_(\d+)\]", "#### Speaker \\1", transcript_text)

        return formatted_transcript_text

    def _attempt_to_map_speaker_names(self, transcript: str, interviewee_emails: list[str]) -> dict[str, str] | None:
        participant_emails_joined = "\n".join(f"- {email}" for email in interviewee_emails)
        assignment_response = OpenAI(
            posthog_client=posthoganalytics.default_client, base_url=settings.OPENAI_BASE_URL
        ).responses.create(  # type: ignore
            model="gpt-4.1-mini",
            posthog_trace_id=self._ai_trace_id,
            posthog_distinct_id=self.context["request"].user.distinct_id,
            input=[
                {
                    "role": "system",
                    "content": """
Your task is to map speakers in a transcript to the actual names of the people who spoke. Each speaker is identified by a number.
Use clues such as who the speaker is calling out (e.g. they wouldn't greet themselves) or what they're talking about (e.g. how they use company names).

Your output should be a JSON mapping between "speaker_<n>" and "<speaker name>".

<handling_ambiguity>
- Use just the person's display name if available, otherwise use their email. If two people with the same full name are present, include their email to disambiguate.
- Likely many of the participants have spoken, but not necessarily all of them.
- Keep in mind it's possible there were additional unexpected participants (though not that likely).
- The transcript is not going to be perfect, so some names in the transcript may be slightly mangled compared to display names in participant emails.
  E.g. the transcript may contain that an interviewer greeted "Jon", but if the participant emails only have a "John", it's safe to assume that the interviewer was talking to John.
- If most of the speakers are entirely obvious, but only a small subset isn't, mark the unidentified speakers' names as "Unknown #1 (<candidate_1> or <candidate_2>)" etc. Don't leave any speaker unmarked.
  If however you cannot infer a reliable mapping for most speakers (the transcript has no useful information or is too chaotic), return simply: null.
</handling_ambiguity>

<example>
As an example, for transcript:

<participant_emails>
- Michael F. Doe <michael@x.com>
- Steve Jobs <steve@apple.com>
</participant_emails>
<transcript>
[speaker_0]
Hi Michael! How big is your company?

[speaker_1]
Hey! We're about 200 people.

[speaker_0]
That's great!
</transcript>

Your output should be:

{
"speaker_0": "Steve Jobs",
"speaker_1": "Michael F. Doe"
}
</example>

<output_format>
Output must always be valid JSON - either an object or null.
</output_format>
""".strip(),
                },
                {
                    "role": "user",
                    "content": f"""
Map the speakers in the following transcript:

<participant_emails>
{participant_emails_joined}
</participant_emails>

<transcript>
{transcript}
</transcript>
""".strip(),
                },
            ],
        )
        try:
            return json.loads(assignment_response.output_text)
        except json.JSONDecodeError as e:
            posthoganalytics.capture_exception(e)
            return None

    def _summarize_transcript(self, transcript: str) -> str:
        summary_response = OpenAI(posthog_client=posthoganalytics.default_client).responses.create(  # type: ignore
            model="gpt-4.1-mini",
            posthog_trace_id=self._ai_trace_id,
            posthog_distinct_id=self.context["request"].user.distinct_id,
            input=[
                {
                    "role": "system",
                    "content": """
You are an expert product manager, and your sole task is to summarizes user interviews ran by our team.
""".strip(),
                },
                {
                    "role": "user",
                    "content": f"""
I interviewed a user to gather insights about our product. The goal is to capture the customer's feedback, experiences, and suggestions in a detailed and organized manner.
The notes should be comprehensive but focused, allowing for the detailed documentation of both qualitative insights and actionable items.
Pull out direct quotes and figures whenever relevant.

Because no better transcript is available, you should still do your best to summarize the interview.

<summary_format>
## User background

Capture relevant details about the user, including their role, experience, and how they interact with your product or service.
Note down here any existing solutions or workarounds they use.

## Current product usage

Document how the user is currently using the product, including frequency of use, key features used, and any specific use cases.

## Positive feedback and pain points

Summarize the positive feedback the user provided, as well as any pain points or challenges they are experiencing with the product.

## Impact of the product

Record the impact the product has had on the user's work or life, including any improvements or changes it has enabled.

## Next steps and follow-up

Record the agreed-upon next steps, including any additional actions that need to be taken, follow-up tasks, and who is responsible for them.
</summary_format>

<transcript>
{transcript}
</transcript>
""".strip(),
                },
            ],
        )
        return summary_response.output_text

    @cached_property
    def _ai_trace_id(self) -> str:
        return str(uuid4())


SEARCH_EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072.value
SEARCH_CONTENT_SNIPPET_LIMIT = 500
SEARCH_MAX_LIMIT = 50
SEARCH_DEFAULT_LIMIT = 10
# Pathological-size guard for topic_id-scoped searches — a topic with more than this many
# interviews ships a giant IN list to ClickHouse. Realistic topics are tiny (<100); the
# cap exists to keep the worst case bounded.
SEARCH_TOPIC_INTERVIEW_CAP = 1000


class UserInterviewSearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=2000,
        help_text="Natural-language query to match semantically against interview transcripts and summaries.",
    )
    document_types = serializers.ListField(
        child=serializers.ChoiceField(choices=list(SEARCH_DOCUMENT_TYPES)),
        required=False,
        allow_empty=False,
        min_length=1,
        help_text=(
            "Which document types to search across. Omit to default to both "
            "`transcript` and `summary`. Pass a non-empty subset to restrict the search."
        ),
    )
    topic_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional. Restrict results to interviews belonging to a specific UserInterviewTopic.",
    )
    classifications = serializers.ListField(
        child=serializers.ChoiceField(choices=UserInterviewClassification.choices),
        required=False,
        allow_empty=False,
        min_length=1,
        help_text=(
            "Optional. Restrict results to interviews carrying any of these classifications (OR). "
            "Combines with `topic_id` as AND."
        ),
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=SEARCH_MAX_LIMIT,
        help_text=(
            f"Maximum number of matches to return (1-{SEARCH_MAX_LIMIT}). "
            f"Defaults to {SEARCH_DEFAULT_LIMIT}. Two matches per interview are possible — "
            "one for the transcript, one for the summary."
        ),
    )


class UserInterviewSearchResultSerializer(serializers.Serializer):
    interview_id = serializers.UUIDField(help_text="ID of the matched UserInterview.")
    document_type = serializers.ChoiceField(
        choices=list(SEARCH_DOCUMENT_TYPES),
        help_text="Which document type matched — `transcript` is the raw conversation, `summary` is the AI-generated abstract.",
    )
    similarity = serializers.FloatField(
        help_text="Cosine similarity in [0, 1]; higher is closer to the query. Computed as `1 - cosineDistance`.",
    )
    content_snippet = serializers.CharField(
        help_text=f"Excerpt of the matched document (first {SEARCH_CONTENT_SNIPPET_LIMIT} characters).",
    )
    interviewee_identifier = serializers.CharField(
        help_text="Email or PostHog distinct ID of the interviewee.",
    )
    topic_id = serializers.UUIDField(
        allow_null=True,
        help_text="ID of the UserInterviewTopic the interview was conducted for, or null if detached.",
    )
    created_at = serializers.DateTimeField(help_text="When the interview row was created.")


class UserInterviewFilterSet(django_filters.FilterSet):
    classifications = django_filters.CharFilter(
        method="filter_classifications",
        help_text=(
            "Comma-separated classifications; returns responses carrying any of them (OR). "
            "Valid values: abandoned, off-topic."
        ),
    )

    class Meta:
        model = UserInterview
        fields = ["topic"]

    def filter_classifications(self, queryset: Any, name: str, value: str) -> Any:
        wanted = [t.strip() for t in value.split(",") if t.strip()]
        if not wanted:
            return queryset
        unknown = [c for c in wanted if c not in UserInterviewClassification.values]
        if unknown:
            valid = ", ".join(UserInterviewClassification.values)
            raise ValidationError(
                {"classifications": f"Unknown classification(s): {', '.join(unknown)}. Valid values: {valid}."}
            )
        return queryset.filter(classifications__overlap=wanted)


class UserInterviewViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "user_interview"
    queryset = UserInterview.objects.order_by("-created_at").select_related("created_by").all()
    serializer_class = UserInterviewSerializer
    parser_classes = [MultiPartParser, JSONParser]
    posthog_feature_flag = "user-interviews"
    permission_classes = [PostHogFeatureFlagPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_class = UserInterviewFilterSet

    @validated_request(
        request_serializer=UserInterviewSearchRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=UserInterviewSearchResultSerializer(many=True),
                description="Matches ranked by cosine similarity (descending).",
            ),
        },
        summary="Search interview responses by semantic similarity",
        description=(
            "Embed `query` with the same model used to index interview transcripts and summaries, "
            "then return the top matches by cosine distance. Each match is a single (interview, "
            "document_type) pair — an interview can appear up to twice if both its transcript and "
            "summary score above other interviews. Useful for surfacing relevant interview snippets "
            "in natural language, without exact keyword matches."
        ),
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="search",
        pagination_class=None,
        parser_classes=[JSONParser],
        required_scopes=["user_interview:read"],
    )
    def search(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> response.Response:
        body = request.validated_data
        query_str: str = body["query"]
        document_types: list[str] = body.get("document_types") or list(SEARCH_DOCUMENT_TYPES)
        topic_id = body.get("topic_id")
        classifications: list[str] = body.get("classifications") or []
        limit: int = body.get("limit") or SEARCH_DEFAULT_LIMIT

        # When a topic_id or classifications filter is requested, resolve it via the current
        # Postgres linkage rather than the embedding-time `metadata.topic_id` — UserInterview.topic
        # is nullable with on_delete=SET_NULL, so historical metadata can name a topic the
        # row no longer belongs to, and classifications are mutated post-embedding.
        scoped_document_ids: list[str] | None = None
        if topic_id is not None or classifications:
            scoped_qs = UserInterview.objects.filter(team_id=self.team_id)
            if topic_id is not None:
                scoped_qs = scoped_qs.filter(topic_id=topic_id)
            if classifications:
                scoped_qs = scoped_qs.filter(classifications__overlap=classifications)
            scoped_ids_qs = scoped_qs.order_by("id").values_list("id", flat=True)[: SEARCH_TOPIC_INTERVIEW_CAP + 1]
            scoped_document_ids = [str(pk) for pk in scoped_ids_qs]
            if not scoped_document_ids:
                return response.Response(UserInterviewSearchResultSerializer([], many=True).data)
            if len(scoped_document_ids) > SEARCH_TOPIC_INTERVIEW_CAP:
                logger.warning(
                    "user_interviews_search_topic_scope_capped",
                    team_id=self.team_id,
                    topic_id=str(topic_id) if topic_id is not None else None,
                    classifications=classifications or None,
                    cap=SEARCH_TOPIC_INTERVIEW_CAP,
                )
                scoped_document_ids = scoped_document_ids[:SEARCH_TOPIC_INTERVIEW_CAP]

        try:
            embedding_response = generate_embedding(self.team, query_str, model=SEARCH_EMBEDDING_MODEL)
        except Exception:
            logger.exception(
                "user_interviews_search_embedding_failed",
                team_id=self.team_id,
                query_length=len(query_str),
            )
            return response.Response(
                {"detail": "Embedding service is currently unavailable. Please retry shortly."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        query_vector = embedding_response.embedding

        where_clauses = [
            "model_name = {model_name}",
            "product = {product}",
            "team_id = {team_id}",
            "document_type IN {document_types}",
        ]
        placeholders: dict[str, ast.Expr] = {
            "embedding": ast.Constant(value=query_vector),
            "model_name": ast.Constant(value=SEARCH_EMBEDDING_MODEL),
            "product": ast.Constant(value=Product.USER_INTERVIEWS.value),
            "team_id": ast.Constant(value=self.team_id),
            "document_types": ast.Constant(value=document_types),
            "limit": ast.Constant(value=limit),
        }
        if scoped_document_ids is not None:
            where_clauses.append("document_id IN {scoped_document_ids}")
            placeholders["scoped_document_ids"] = ast.Constant(value=scoped_document_ids)

        # The embedding row is used only for ranking and routing. The snippet itself is
        # built from the current Postgres UserInterview field so edits/deletions to the
        # source content are reflected immediately — otherwise an embedding written before
        # an edit would leak the previous text via the search endpoint.
        hogql_query = f"""
            SELECT
                document_id,
                document_type,
                cosineDistance(embedding, {{embedding}}) AS distance
            FROM document_embeddings
            WHERE {" AND ".join(where_clauses)}
            ORDER BY distance ASC
            LIMIT {{limit}}
        """

        tag_queries(product=Product.USER_INTERVIEWS, feature=Feature.SEMANTIC_SEARCH)
        query_result = execute_hogql_query(
            query=hogql_query,
            team=self.team,
            placeholders=placeholders,
        )

        rows = query_result.results or []
        document_ids = {row[0] for row in rows}
        interviews_by_id = {
            str(i.id): i
            for i in UserInterview.objects.filter(team_id=self.team_id, id__in=document_ids).only(
                "id", "interviewee_identifier", "topic_id", "created_at", "transcript", "summary"
            )
        }

        results: list[dict[str, Any]] = []
        for document_id, document_type, distance in rows:
            interview = interviews_by_id.get(document_id)
            if interview is None:
                continue
            live_content = interview.transcript if document_type == "transcript" else interview.summary
            results.append(
                {
                    "interview_id": interview.id,
                    "document_type": document_type,
                    "similarity": min(1.0, max(0.0, 1.0 - float(distance))),
                    "content_snippet": (live_content or "")[:SEARCH_CONTENT_SNIPPET_LIMIT],
                    "interviewee_identifier": interview.interviewee_identifier,
                    "topic_id": interview.topic_id,
                    "created_at": interview.created_at,
                }
            )

        return response.Response(UserInterviewSearchResultSerializer(results, many=True).data)


class UserInterviewTopicSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    interviewee_emails = serializers.ListField(
        child=serializers.CharField(max_length=254, validators=[EmailWithDisplayNameValidator()]),
        required=False,
        help_text="Email addresses of people to interview. May be combined with interviewee_distinct_ids.",
    )
    interviewee_distinct_ids = serializers.ListField(
        child=serializers.CharField(max_length=400),
        required=False,
        help_text="PostHog distinct IDs of people to interview. May be combined with interviewee_emails.",
    )
    topic = serializers.CharField(
        help_text="The product, feature, or idea you want to ask interviewees about.",
    )
    agent_context = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional additional system prompt for the voice agent — extra background, tone, or constraints.",
    )
    questions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Ordered list of questions the voice agent should work through during the interview.",
    )
    invite_subject = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text=(
            "Subject line for the invitation email. Plain text only — URLs, angle brackets, and control "
            "characters are rejected. Leave blank to use the default subject. Personalization is handled by "
            "the email template, so do not include placeholders."
        ),
    )
    invite_message = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text=(
            "Intro message shown in the invitation email body, above the interview link. Plain prose only — "
            "URLs, angle brackets, and control characters are rejected (line breaks are allowed). Leave blank "
            "to use the default copy."
        ),
    )

    class Meta:
        model = UserInterviewTopic
        fields = (
            "id",
            "created_by",
            "created_at",
            "interviewee_emails",
            "interviewee_distinct_ids",
            "topic",
            "agent_context",
            "questions",
            "invite_subject",
            "invite_message",
        )
        read_only_fields = ("id", "created_by", "created_at")

    def validate_invite_subject(self, value: str | None) -> str | None:
        return validate_invite_subject(value)

    def validate_invite_message(self, value: str | None) -> str | None:
        return validate_invite_message(value)

    MISSING_TARGETING_ERROR = "At least one of interviewee_emails or interviewee_distinct_ids must be provided."

    def validate(self, attrs: dict) -> dict:
        if not self._current(attrs, "interviewee_emails", []) and not self._current(
            attrs, "interviewee_distinct_ids", []
        ):
            raise serializers.ValidationError(self.MISSING_TARGETING_ERROR)
        return attrs

    def _current(self, attrs: dict, field: str, default: Any) -> Any:
        if field in attrs:
            return attrs[field]
        return getattr(self.instance, field, default)

    def create(self, validated_data: dict) -> UserInterviewTopic:
        request = self.context["request"]
        team = self.context["get_team"]()
        return UserInterviewTopic.objects.create(
            team=team,
            created_by=request.user,
            **validated_data,
        )

    def update(self, instance: UserInterviewTopic, validated_data: dict) -> UserInterviewTopic:
        old_emails = set(instance.interviewee_emails or [])
        old_distinct_ids = set(instance.interviewee_distinct_ids or [])
        # Atomic so the topic save and the share-revoke commit together. Without this,
        # a crash between the two writes would leave an interviewee removed from targeting
        # but still able to open their existing public interview link.
        with transaction.atomic():
            topic = super().update(instance, validated_data)
            new_emails = set(topic.interviewee_emails or [])
            new_distinct_ids = set(topic.interviewee_distinct_ids or [])
            removed = (old_emails - new_emails) | (old_distinct_ids - new_distinct_ids)
            _disable_shares_for_identifiers(topic=topic, identifiers=sorted(removed))
        return topic


def _parse_identifier(identifier: str) -> tuple[str, str | None]:
    """Tuple-shaped shim around the facade's identifier parser for legacy internal callers."""
    identity = parse_interviewee_identifier(identifier)
    return identity.display_name, identity.email


def _merge_agent_context(topic_context: str, personal_context: str) -> str:
    parts = [p.strip() for p in (topic_context, personal_context) if p and p.strip()]
    return "\n\n".join(parts)


class LatestTestInterviewSerializer(serializers.Serializer):
    completed_at = serializers.DateTimeField(
        help_text="When the test interview was completed.",
    )
    transcript = serializers.CharField(
        allow_blank=True,
        help_text="Full transcript of the test call, if Vapi delivered one. May be empty.",
    )
    summary = serializers.CharField(
        allow_blank=True,
        help_text="AI-generated summary of the test call, if Vapi delivered one. May be empty.",
    )


class TestInterviewLinkSerializer(serializers.Serializer):
    interview_url = serializers.URLField(
        help_text=(
            "Public, unauthenticated URL the topic author opens to dogfood the voice "
            "interview themselves — does not count against the targeted interviewees."
        ),
    )
    latest_test_interview = LatestTestInterviewSerializer(
        allow_null=True,
        help_text="Most recent test interview completed by the topic author, or null if none yet.",
    )


class InterviewLinkSerializer(serializers.Serializer):
    interviewee_identifier = serializers.CharField(
        max_length=400,
        help_text="The original identifier (email or distinct ID) from the topic targeting.",
    )
    user_name = serializers.CharField(
        help_text="Best-effort display name derived from the identifier, used to greet the interviewee.",
    )
    interview_url = serializers.URLField(
        help_text="Public, unauthenticated URL the interviewee opens to start the call. Backed by a SharingConfiguration access token.",
    )
    agent_context = serializers.CharField(
        help_text="The merged topic + per-interviewee context the voice agent will see during the call.",
    )


def _dogfood_identifier(caller: User) -> str:
    """Identifier for the calling user's personal dogfood interviewee context.

    Prefers the user's email so the existing identifier-parsing surfaces a friendly
    display name in the assistant greeting; falls back to their distinct_id so a
    user without a real email still gets a working test link.
    """
    return caller.email or str(caller.distinct_id)


def _ensure_dogfood_context(
    *, topic: UserInterviewTopic, team: Team, caller: User
) -> tuple[IntervieweeContext, SharingConfiguration]:
    """Idempotently get-or-create the calling user's `IntervieweeContext` +
    enabled `SharingConfiguration` for a topic. The IC is keyed on the caller's
    own identifier so each team member gets their own dogfood link — we never
    mint a public share token in someone else's name.

    Wrapped in `transaction.atomic` + `select_for_update` on the IC row so two
    concurrent calls don't race into duplicate enabled SharingConfigurations
    for the same (caller, topic).
    """
    identifier = _dogfood_identifier(caller)
    with transaction.atomic():
        ic, _ = IntervieweeContext.objects.select_for_update().get_or_create(
            team=team,
            topic=topic,
            interviewee_identifier=identifier,
            defaults={
                "agent_context": "",
                "created_by": caller,
            },
        )
        sharing_config = (
            SharingConfiguration.objects.filter(team=team, interviewee_context=ic, enabled=True)
            .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now()))
            .order_by("-created_at")
            .first()
        )
        if sharing_config is None:
            sharing_config = SharingConfiguration.objects.create(
                team=team,
                interviewee_context=ic,
                enabled=True,
            )
    return ic, sharing_config


def _materialize_links_for_topic(*, topic: UserInterviewTopic, team: Any, created_by: Any) -> list[dict[str, Any]]:
    """Get-or-create an `IntervieweeContext` and enabled `SharingConfiguration` for every
    targeted identifier on the topic. Returns one row per identifier with the resolved
    objects attached so callers (link-listing, invite-sending) can fan out without re-querying.

    Race-safe: concurrent calls for the same (topic, identifier) rely on the
    `unique_interviewee_per_topic` constraint (Paul's migration 0003) to coalesce. The
    `SharingConfiguration` lookup is best-effort and may transiently produce two configs
    on a tight race — that's acceptable since both are valid and one wins the next call.
    """
    identifiers: list[str] = []
    seen: set[str] = set()
    for raw in [*(topic.interviewee_emails or []), *(topic.interviewee_distinct_ids or [])]:
        if raw and raw not in seen:
            identifiers.append(raw)
            seen.add(raw)

    if not identifiers:
        return []

    results: list[dict[str, Any]] = []
    for identifier in identifiers:
        ic, _ = IntervieweeContext.objects.get_or_create(
            team=team,
            topic=topic,
            interviewee_identifier=identifier,
            defaults={"agent_context": "", "created_by": created_by},
        )

        sharing_config = (
            SharingConfiguration.objects.filter(team=team, interviewee_context=ic, enabled=True)
            .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now()))
            .order_by("-created_at")
            .first()
        )
        if sharing_config is None:
            sharing_config = SharingConfiguration.objects.create(
                team=team,
                interviewee_context=ic,
                enabled=True,
            )

        user_name, email = _parse_identifier(identifier)
        results.append(
            {
                "identifier": identifier,
                "user_name": user_name,
                "email": email,
                "interview_url": absolute_uri(f"/interview/{sharing_config.access_token}"),
                "agent_context": _merge_agent_context(topic.agent_context or "", ic.agent_context or ""),
                "interviewee_context": ic,
                "sharing_configuration": sharing_config,
            }
        )
    return results


class InterviewInviteResultSerializer(serializers.Serializer):
    interviewee_identifier = serializers.CharField(
        help_text="The original identifier (email or distinct ID) from the topic targeting.",
    )
    email = serializers.EmailField(
        required=False,
        allow_null=True,
        help_text="Email used for delivery. Null when the identifier was not an email (e.g., a distinct ID).",
    )
    interview_url = serializers.URLField(
        help_text="The personalized public interview URL embedded in the email body.",
    )
    sent = serializers.BooleanField(
        help_text="True if an email was queued for delivery. False when the recipient was skipped — see `reason`.",
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Why the email was skipped (e.g., `not_an_email`, `duplicate_recipient`, `already_sent`). "
            "Empty when sent=true."
        ),
    )


# Mirrors the column max_length on UserInterviewTopic.interviewee_emails — anything longer
# would pass request validation and then fail at INSERT time with a 500. Keep in sync.
EMAIL_IDENTIFIER_MAX_LENGTH = 254
DISTINCT_ID_IDENTIFIER_MAX_LENGTH = 400


def _identifier_is_email(identifier: str) -> bool:
    try:
        EmailWithDisplayNameValidator()(identifier)
    except DjangoValidationError:
        return False
    return True


class IntervieweeIdentifierRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(
        max_length=DISTINCT_ID_IDENTIFIER_MAX_LENGTH,
        help_text=(
            "Email address or PostHog distinct ID for the interviewee. Email-shaped values "
            "(including the `Display Name <email@host>` form) are routed to `interviewee_emails`; "
            "everything else lands in `interviewee_distinct_ids`."
        ),
    )

    def validate_identifier(self, value: str) -> str:
        if _identifier_is_email(value) and len(value) > EMAIL_IDENTIFIER_MAX_LENGTH:
            raise serializers.ValidationError(
                f"Email identifiers must be {EMAIL_IDENTIFIER_MAX_LENGTH} characters or fewer."
            )
        return value


def _disable_shares_for_identifiers(*, topic: UserInterviewTopic, identifiers: list[str]) -> None:
    """Disable any active SharingConfiguration tied to the given identifiers on a topic.

    Used by remove_interviewee, and by topic partial_update when identifiers are dropped
    from the targeting arrays — so a person removed via either path can no longer open
    their existing public interview link.
    """
    if not identifiers:
        return
    SharingConfiguration.objects.filter(
        team_id=topic.team_id,
        interviewee_context__topic=topic,
        interviewee_context__interviewee_identifier__in=identifiers,
        enabled=True,
    ).update(enabled=False)


MAX_INVITE_RECIPIENTS_PER_SEND = 500


class SendInvitesRequestSerializer(serializers.Serializer):
    subject = serializers.CharField(
        required=False,
        max_length=200,
        help_text=(
            "Override the email subject line for this send. Plain text only — URLs, angle brackets, and "
            "control characters are rejected. Falls back to the topic's saved subject, then a default."
        ),
    )
    reply_to = serializers.EmailField(
        required=False,
        help_text="Email address replies should go to. Defaults to the topic creator's email if blank.",
    )
    send_async = serializers.BooleanField(
        required=False,
        default=True,
        help_text="If true (default), queue delivery via Celery. If false, send synchronously and surface errors immediately.",
    )

    def validate_subject(self, value: str | None) -> str | None:
        return validate_invite_subject(value)


class PreviewInviteRequestSerializer(serializers.Serializer):
    interviewee_identifier = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=400,
        help_text=(
            "Which targeted interviewee to render the preview for (an email or PostHog distinct ID "
            "already on the topic). Leave blank to preview for the first targeted interviewee."
        ),
    )


class PreviewInviteResultSerializer(serializers.Serializer):
    interviewee_identifier = serializers.CharField(
        help_text="The identifier (email or distinct ID) the preview was rendered for.",
    )
    user_name = serializers.CharField(
        help_text="The display name used in the email greeting, derived from the identifier.",
    )
    email = serializers.EmailField(
        allow_null=True,
        help_text="The email address the invite would be sent to. Null for distinct-ID-only interviewees.",
    )
    subject = serializers.CharField(
        help_text="The rendered subject line (saved topic subject, sanitized, or the default).",
    )
    html = serializers.CharField(
        help_text="The fully rendered, CSS-inlined HTML body of the invite email. Safe to display in a sandboxed iframe.",
    )
    interview_url = serializers.URLField(
        help_text=(
            "An illustrative placeholder interview link shown in the previewed email body. The preview "
            "never exposes a real per-recipient share token — that link is minted only when invites are sent."
        ),
    )
    emailable = serializers.BooleanField(
        help_text="True if this interviewee has an email address and could actually receive the invite.",
    )
    is_preview_link = serializers.BooleanField(
        help_text="Always true — the previewed interview_url is an illustrative placeholder, never a live link.",
    )


class UserInterviewTopicViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Planned user interview topics: who we want to target and what we want to ask about."""

    scope_object = "user_interview"
    # Treat the custom @action endpoints as writes so personal API keys with
    # `user_interview:write` can hit them. Without this override, APIScopePermission
    # can't map a custom action name to a scope and rejects the request with
    # "This action does not support personal API key access".
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "generate_links",
        "links_csv",
        "send_invites",
        "add_interviewee",
        "remove_interviewee",
        "test_link",
    ]
    # preview_invite is a POST (body carries the identifier, keeping emails out of query-string logs)
    # but renders read-only with no side effects, so it maps to the read scope. Keep the default read
    # actions (list/retrieve) — this list REPLACES the default, so omitting them would drop read-scope
    # access for token-authenticated list/retrieve.
    scope_object_read_actions = [
        "list",
        "retrieve",
        "preview_invite",
    ]
    queryset = UserInterviewTopic.objects.select_related("created_by").all()
    serializer_class = UserInterviewTopicSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["topic"]
    posthog_feature_flag = "user-interviews"
    permission_classes = [PostHogFeatureFlagPermission]

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(response=InterviewLinkSerializer(many=True))},
        description=(
            "Generate one public interview link per targeted interviewee. "
            "Materializes an IntervieweeContext row for every identifier on the topic "
            "(without overwriting existing per-person context), and an enabled "
            "SharingConfiguration with a unique access token. The URL resolves to the "
            "public interview viewer with no PostHog auth required."
        ),
    )
    @action(detail=True, methods=["post"], url_path="generate_links")
    def generate_links(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        topic = self.get_object()
        results = _materialize_links_for_topic(topic=topic, team=self.team, created_by=request.user)

        if not results:
            return response.Response(
                {
                    "error": (
                        "Topic has no interviewee_emails or interviewee_distinct_ids set. "
                        "Add them before generating links."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = [
            {
                "interviewee_identifier": r["identifier"],
                "user_name": r["user_name"],
                "interview_url": r["interview_url"],
                "agent_context": r["agent_context"],
            }
            for r in results
        ]
        return response.Response(InterviewLinkSerializer(payload, many=True).data)

    @extend_schema(
        request=None,
        responses={
            (200, "text/csv"): OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description=(
                    "CSV with columns: interviewee_identifier, interviewee_email, user_name, interview_url. "
                    "One row per targeted interviewee."
                ),
            )
        },
        description=(
            "Same materialization as generate_links, returned as a downloadable CSV. "
            "Intended for users who want to mail-merge the per-person interview links "
            "into their own email tooling."
        ),
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="links_csv",
        renderer_classes=[_InterviewLinksCSVRenderer],
    )
    def links_csv(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        topic = self.get_object()
        results = _materialize_links_for_topic(topic=topic, team=self.team, created_by=request.user)

        if not results:
            raise ValidationError(
                {
                    "error": (
                        "Topic has no interviewee_emails or interviewee_distinct_ids set. "
                        "Add them before generating links."
                    )
                }
            )

        rows = [
            {
                "interviewee_identifier": sanitize_formula_injection(r["identifier"]),
                "interviewee_email": sanitize_formula_injection(r["email"] or ""),
                "user_name": sanitize_formula_injection(r["user_name"]),
                "interview_url": sanitize_formula_injection(r["interview_url"]),
            }
            for r in results
        ]
        filename = f"{slugify(topic.topic or 'user-interview')}-links.csv"
        return response.Response(
            rows,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @extend_schema(
        request=SendInvitesRequestSerializer,
        responses={200: OpenApiResponse(response=InterviewInviteResultSerializer(many=True))},
        description=(
            "Generate (if needed) and email a personalized public interview link to every "
            "targeted interviewee on this topic whose identifier is an email address. "
            "Distinct-ID-only interviewees are skipped and surfaced in the response. "
            "Each invite is keyed on the underlying SharingConfiguration so re-runs after "
            "token rotation produce a fresh send."
        ),
    )
    @action(detail=True, methods=["post"], url_path="send_invites", throttle_classes=[UserInterviewInviteThrottle])
    def send_invites(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        if not is_email_available():
            return response.Response(
                {"error": "Email is not configured for this PostHog instance."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        params = SendInvitesRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)

        topic = self.get_object()
        # Enforce the cap on targeted identifiers BEFORE materializing share links, so an oversized
        # topic is rejected without first minting an IntervieweeContext + SharingConfiguration for
        # every target. dict.fromkeys dedups while preserving order, matching _materialize_links_for_topic.
        targeted_identifiers = list(
            dict.fromkeys(
                raw for raw in [*(topic.interviewee_emails or []), *(topic.interviewee_distinct_ids or [])] if raw
            )
        )
        if not targeted_identifiers:
            return response.Response(
                {
                    "error": (
                        "Topic has no interviewee_emails or interviewee_distinct_ids set. "
                        "Add them before sending invites."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(targeted_identifiers) > MAX_INVITE_RECIPIENTS_PER_SEND:
            return response.Response(
                {
                    "error": (
                        f"Topic targets {len(targeted_identifiers)} interviewees, more than the per-send limit of "
                        f"{MAX_INVITE_RECIPIENTS_PER_SEND}. Split the targeting across multiple topics."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        links = _materialize_links_for_topic(topic=topic, team=self.team, created_by=request.user)

        subject_override = params.validated_data.get("subject") or ""
        reply_to = params.validated_data.get("reply_to")
        if not reply_to and topic.created_by_id and topic.created_by and topic.created_by.email:
            reply_to = topic.created_by.email
        send_async = params.validated_data["send_async"]

        results: list[dict[str, Any]] = []
        seen_emails: set[str] = set()
        for link in links:
            base = {
                "interviewee_identifier": link["identifier"],
                "email": link["email"],
                "interview_url": link["interview_url"],
            }
            if not link["email"]:
                results.append({**base, "sent": False, "reason": "not_an_email"})
                continue

            # Collapse display-name aliases that resolve to the same mailbox (e.g.
            # "A1 <x@host>" and "A2 <x@host>") so one mailbox can't be invited repeatedly.
            email_key = link["email"].strip().lower()
            if email_key in seen_emails:
                results.append({**base, "sent": False, "reason": "duplicate_recipient"})
                continue
            seen_emails.add(email_key)

            built = build_invite_email_context(
                topic=topic,
                user_name=link["user_name"],
                interview_url=link["interview_url"],
                subject_override=subject_override,
            )
            campaign_key = f"interview_invite_{link['sharing_configuration'].id}"
            try:
                message = EmailMessage(
                    campaign_key=campaign_key,
                    template_name="interview_invite",
                    subject=built["subject"],
                    template_context=built["template_context"],
                    reply_to=reply_to,
                )
                message.add_recipient(email=link["email"], name=link["user_name"])
                message.send(send_async=send_async)
                results.append({**base, "sent": True, "reason": ""})
            except Exception as e:  # noqa: BLE001 — surface per-recipient failures without aborting the batch
                posthoganalytics.capture_exception(e)
                results.append({**base, "sent": False, "reason": f"error:{type(e).__name__}"})

        return response.Response(InterviewInviteResultSerializer(results, many=True).data)

    @extend_schema(
        request=PreviewInviteRequestSerializer,
        responses={200: OpenApiResponse(response=PreviewInviteResultSerializer)},
        description=(
            "Render the invite email exactly as a specific targeted interviewee would receive it — "
            "personalized subject and body — without sending anything and without creating or reading "
            "any share links. Pass `interviewee_identifier` to preview for a particular person, or omit "
            "it to preview for the first targeted interviewee. The body always shows an illustrative "
            "placeholder link (`is_preview_link: true`), never a live interview URL."
        ),
    )
    @action(detail=True, methods=["post"], url_path="preview_invite")
    def preview_invite(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        params = PreviewInviteRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)

        topic = self.get_object()
        payload = resolve_invite_preview(
            topic=topic,
            interviewee_identifier=params.validated_data.get("interviewee_identifier") or "",
        )
        if payload is None:
            return response.Response(
                {
                    "error": (
                        "Topic has no targeted interviewees, or the given interviewee_identifier is not "
                        "one of this topic's interviewee_emails / interviewee_distinct_ids."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return response.Response(PreviewInviteResultSerializer(payload).data)

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(response=TestInterviewLinkSerializer)},
        description=(
            "Return the calling user's personal dogfood interview link for this topic, "
            "plus the latest test interview they have recorded against it. Lazily "
            "get-or-creates a per-caller IntervieweeContext + enabled SharingConfiguration "
            "the first time it's called, then returns the same stable URL on subsequent "
            "calls. The caller's identifier is intentionally not added to the topic's "
            "targeting arrays — each user dogfoods under their own row, so test calls "
            "never mint a public share token on someone else's behalf."
        ),
    )
    @action(detail=True, methods=["get"], url_path="test_link")
    def test_link(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        topic = self.get_object()
        ic, sharing_config = _ensure_dogfood_context(
            topic=topic,
            team=self.team,
            caller=cast(User, request.user),
        )

        latest = (
            UserInterview.objects.filter(
                team_id=self.team_id,
                topic_id=topic.id,
                interviewee_identifier=ic.interviewee_identifier,
            )
            .order_by("-created_at")
            .only("created_at", "transcript", "summary")
            .first()
        )
        latest_payload: dict[str, Any] | None = None
        if latest is not None:
            latest_payload = {
                "completed_at": latest.created_at,
                "transcript": latest.transcript or "",
                "summary": latest.summary or "",
            }

        payload = {
            "interview_url": absolute_uri(f"/interview/{sharing_config.access_token}"),
            "latest_test_interview": latest_payload,
        }
        return response.Response(TestInterviewLinkSerializer(payload).data)

    @extend_schema(
        request=IntervieweeIdentifierRequestSerializer,
        responses={200: OpenApiResponse(response=UserInterviewTopicSerializer)},
        description=(
            "Add a single interviewee to this topic. Email-shaped identifiers (including the "
            "`Display Name <email@host>` form) are appended to `interviewee_emails`; everything "
            "else is appended to `interviewee_distinct_ids`. Idempotent — adding an identifier "
            "that's already present leaves the topic unchanged. Returns the updated topic."
        ),
    )
    @action(detail=True, methods=["post"], url_path="add_interviewee")
    def add_interviewee(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        params = IntervieweeIdentifierRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        identifier = params.validated_data["identifier"]

        self.get_object()
        with transaction.atomic():
            topic = self.get_queryset().select_for_update(of=("self",)).get(pk=kwargs[self.lookup_field])
            emails = list(topic.interviewee_emails or [])
            distinct_ids = list(topic.interviewee_distinct_ids or [])
            changed = False
            if _identifier_is_email(identifier):
                if identifier not in emails:
                    emails.append(identifier)
                    changed = True
            elif identifier not in distinct_ids:
                distinct_ids.append(identifier)
                changed = True

            if changed:
                topic.interviewee_emails = emails
                topic.interviewee_distinct_ids = distinct_ids
                topic.save(update_fields=["interviewee_emails", "interviewee_distinct_ids"])

        serializer = UserInterviewTopicSerializer(topic, context=self.get_serializer_context())
        return response.Response(serializer.data)

    @extend_schema(
        request=IntervieweeIdentifierRequestSerializer,
        responses={200: OpenApiResponse(response=UserInterviewTopicSerializer)},
        description=(
            "Remove an interviewee from this topic. Drops the identifier from both "
            "`interviewee_emails` and `interviewee_distinct_ids`, and disables any active "
            "SharingConfiguration linked to an IntervieweeContext for that identifier on this "
            "topic so the removed person can no longer open their interview link. Idempotent — "
            "removing an identifier that isn't present is a no-op. Returns the updated topic."
        ),
    )
    @action(detail=True, methods=["post"], url_path="remove_interviewee")
    def remove_interviewee(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        params = IntervieweeIdentifierRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        identifier = params.validated_data["identifier"]

        self.get_object()
        with transaction.atomic():
            topic = self.get_queryset().select_for_update(of=("self",)).get(pk=kwargs[self.lookup_field])
            new_emails = [e for e in (topic.interviewee_emails or []) if e != identifier]
            new_distinct_ids = [d for d in (topic.interviewee_distinct_ids or []) if d != identifier]

            if new_emails != list(topic.interviewee_emails or []) or new_distinct_ids != list(
                topic.interviewee_distinct_ids or []
            ):
                topic.interviewee_emails = new_emails
                topic.interviewee_distinct_ids = new_distinct_ids
                topic.save(update_fields=["interviewee_emails", "interviewee_distinct_ids"])

            _disable_shares_for_identifiers(topic=topic, identifiers=[identifier])

        serializer = UserInterviewTopicSerializer(topic, context=self.get_serializer_context())
        return response.Response(serializer.data)


class IntervieweeContextSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    interviewee_identifier = serializers.CharField(
        max_length=400,
        help_text="Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids.",
    )
    agent_context = serializers.CharField(
        max_length=10000,
        help_text="Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'.",
    )

    class Meta:
        model = IntervieweeContext
        fields = (
            "id",
            "created_by",
            "created_at",
            "interviewee_identifier",
            "agent_context",
        )
        read_only_fields = ("id", "created_by", "created_at")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        topic_id = self.context["topic_id"]
        team = self.context["get_team"]()

        if not UserInterviewTopic.objects.filter(id=topic_id, team_id=team.id).exists():
            raise serializers.ValidationError({"topic": "Topic not found in this project."})

        interviewee_identifier = attrs.get("interviewee_identifier")
        if interviewee_identifier is not None:
            conflicts = IntervieweeContext.objects.filter(
                topic_id=topic_id, interviewee_identifier=interviewee_identifier
            )
            if self.instance is not None:
                conflicts = conflicts.exclude(pk=self.instance.pk)
            if conflicts.exists():
                raise serializers.ValidationError(
                    {
                        "interviewee_identifier": "A context row for this interviewee already exists on this topic. Update the existing row instead of creating a new one."
                    }
                )
        return attrs

    def create(self, validated_data: dict[str, Any]) -> IntervieweeContext:
        request = self.context["request"]
        team = self.context["get_team"]()
        topic_id = self.context["topic_id"]
        return IntervieweeContext.objects.create(
            team=team,
            topic_id=topic_id,
            created_by=request.user,
            **validated_data,
        )


BULK_INTERVIEWEE_CONTEXT_MAX_ITEMS = 500


class BulkIntervieweeContextItemSerializer(serializers.Serializer):
    interviewee_identifier = serializers.CharField(
        max_length=400,
        help_text="Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids.",
    )
    agent_context = serializers.CharField(
        max_length=10000,
        help_text="Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'.",
    )


class BulkIntervieweeContextRequestSerializer(serializers.Serializer):
    items = BulkIntervieweeContextItemSerializer(
        many=True,
        allow_empty=False,
        help_text=(
            "List of interviewee context rows to create. Each item has an `interviewee_identifier` and an "
            f"`agent_context`. At most {BULK_INTERVIEWEE_CONTEXT_MAX_ITEMS} items per request."
        ),
    )

    def validate_items(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) > BULK_INTERVIEWEE_CONTEXT_MAX_ITEMS:
            raise serializers.ValidationError(
                f"Cannot create more than {BULK_INTERVIEWEE_CONTEXT_MAX_ITEMS} interviewee contexts in one request."
            )
        identifiers = [item["interviewee_identifier"] for item in value]
        if len(set(identifiers)) != len(identifiers):
            raise serializers.ValidationError("Duplicate interviewee_identifier values within items.")
        return value


class BulkIntervieweeContextResponseSerializer(serializers.Serializer):
    inserted_count = serializers.IntegerField(help_text="Number of rows inserted by this request.")
    skipped_count = serializers.IntegerField(
        help_text="Number of items skipped because a row for that (topic, interviewee_identifier) already existed."
    )
    skipped_identifiers = serializers.ListField(
        child=serializers.CharField(),
        help_text="Identifiers from the request whose rows were skipped because a row for that (topic, interviewee_identifier) already existed.",
    )


class IntervieweeContextViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier)."""

    scope_object = "user_interview"
    # Treat the custom @action endpoints as writes so personal API keys with
    # `user_interview:write` can hit them. Without this override, APIScopePermission
    # can't map a custom action name to a scope and rejects the request with
    # "This action does not support personal API key access".
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "destroy",
        "bulk_create",
    ]
    serializer_class = IntervieweeContextSerializer
    queryset = IntervieweeContext.objects.select_related("created_by").all()
    posthog_feature_flag = "user-interviews"
    permission_classes = [PostHogFeatureFlagPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(
            topic_id=self.parents_query_dict["topic_id"],
            team_id=self.parents_query_dict["team_id"],
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "topic_id": self.parents_query_dict["topic_id"]}

    @extend_schema(
        request=BulkIntervieweeContextRequestSerializer,
        responses={200: OpenApiResponse(response=BulkIntervieweeContextResponseSerializer)},
        description=(
            f"Create up to {BULK_INTERVIEWEE_CONTEXT_MAX_ITEMS} interviewee context rows for a topic in a single "
            "request. Rows whose (topic, interviewee_identifier) already exists are skipped — the response surfaces "
            "an `inserted_count`, a `skipped_count`, and the `skipped_identifiers` so the caller can reconcile. "
            "Items must have unique `interviewee_identifier` values within the batch."
        ),
    )
    @action(detail=False, methods=["post"], url_path="bulk", pagination_class=None)
    def bulk_create(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        topic_id = self.parents_query_dict["topic_id"]
        team_id = self.parents_query_dict["team_id"]

        topic = UserInterviewTopic.objects.filter(id=topic_id, team_id=team_id).first()
        if topic is None:
            return response.Response(
                {"error": "Topic not found in this project."},
                status=status.HTTP_404_NOT_FOUND,
            )
        self.check_object_permissions(request, topic)

        payload = BulkIntervieweeContextRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        items: list[dict[str, Any]] = payload.validated_data["items"]

        identifiers = [item["interviewee_identifier"] for item in items]
        existing = set(
            IntervieweeContext.objects.filter(
                topic_id=topic_id,
                interviewee_identifier__in=identifiers,
            ).values_list("interviewee_identifier", flat=True)
        )

        new_rows = [
            IntervieweeContext(
                team_id=team_id,
                topic_id=topic_id,
                created_by=cast(User, request.user),
                interviewee_identifier=item["interviewee_identifier"],
                agent_context=item["agent_context"],
            )
            for item in items
            if item["interviewee_identifier"] not in existing
        ]

        inserted = IntervieweeContext.objects.bulk_create(new_rows, ignore_conflicts=True)

        response_payload = {
            "inserted_count": len(inserted),
            "skipped_count": len(existing) + (len(new_rows) - len(inserted)),
            "skipped_identifiers": sorted(existing),
        }
        return response.Response(BulkIntervieweeContextResponseSerializer(response_payload).data)
