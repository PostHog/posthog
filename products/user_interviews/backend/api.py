import re
import json
from functools import cached_property
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.core.files import File
from django.db import models
from django.db.models import QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
import posthoganalytics.ai.openai
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema
from elevenlabs import ElevenLabs
from posthoganalytics.ai.openai import OpenAI
from rest_framework import filters, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request

from posthog.schema import EmbeddingModelName, ProductKey

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import generate_embedding
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.email import EmailMessage, is_email_available
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.utils import absolute_uri

from .models import EmailWithDisplayNameValidator, IntervieweeContext, UserInterview, UserInterviewTopic

logger = structlog.get_logger(__name__)

elevenlabs_client = ElevenLabs()


class UserInterviewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    audio = serializers.FileField(write_only=True)

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
        return super().create(validated_data)

    def _transcribe_audio(self, audio: File, interviewee_emails: list[str]) -> str:
        transcript = elevenlabs_client.speech_to_text.convert(
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


SEARCH_DOCUMENT_TYPES = ("transcript", "summary")
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


@extend_schema(tags=[ProductKey.USER_INTERVIEWS])
class UserInterviewViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "user_interview"
    queryset = UserInterview.objects.order_by("-created_at").select_related("created_by").all()
    serializer_class = UserInterviewSerializer
    parser_classes = [MultiPartParser, JSONParser]
    posthog_feature_flag = "user-interviews"
    permission_classes = [PostHogFeatureFlagPermission]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["topic"]

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
        limit: int = body.get("limit") or SEARCH_DEFAULT_LIMIT

        # When a topic_id filter is requested, resolve it via the current Postgres linkage
        # rather than the embedding-time `metadata.topic_id` — UserInterview.topic is
        # nullable with on_delete=SET_NULL, so historical metadata can name a topic the
        # row no longer belongs to.
        scoped_document_ids: list[str] | None = None
        if topic_id is not None:
            scoped_ids_qs = (
                UserInterview.objects.filter(team_id=self.team_id, topic_id=topic_id)
                .order_by("id")
                .values_list("id", flat=True)[: SEARCH_TOPIC_INTERVIEW_CAP + 1]
            )
            scoped_document_ids = [str(pk) for pk in scoped_ids_qs]
            if not scoped_document_ids:
                return response.Response(UserInterviewSearchResultSerializer([], many=True).data)
            if len(scoped_document_ids) > SEARCH_TOPIC_INTERVIEW_CAP:
                logger.warning(
                    "user_interviews_search_topic_scope_capped",
                    team_id=self.team_id,
                    topic_id=str(topic_id),
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
        )
        read_only_fields = ("id", "created_by", "created_at")

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


def _parse_identifier(identifier: str) -> tuple[str, str | None]:
    """Split an interviewee identifier into a display name and (optional) email.

    Accepts the same display-name format the topic validator accepts —
    ``"Display Name <email@host>"`` — falling back to a best-effort
    title-cased local-part for raw emails and the identifier as-is for
    distinct IDs.
    """
    display_match = re.match(EmailWithDisplayNameValidator.display_name_regex, identifier)
    if display_match:
        return display_match.group(1).strip(), display_match.group(2).strip()
    if "@" in identifier:
        local_part = identifier.split("@", 1)[0]
        return local_part.replace(".", " ").replace("_", " ").strip().title() or identifier, identifier
    return identifier, None


def _merge_agent_context(topic_context: str, personal_context: str) -> str:
    parts = [p.strip() for p in (topic_context, personal_context) if p and p.strip()]
    return "\n\n".join(parts)


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
        help_text="Why the email was skipped (e.g., `not_an_email`, `already_sent`). Empty when sent=true.",
    )


class SendInvitesRequestSerializer(serializers.Serializer):
    subject = serializers.CharField(
        required=False,
        max_length=200,
        help_text="Override the default email subject line. Defaults to a friendly prompt referencing the topic.",
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


@extend_schema(tags=[ProductKey.USER_INTERVIEWS])
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
        "send_invites",
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
    @action(detail=True, methods=["post"], url_path="send_invites")
    def send_invites(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        if not is_email_available():
            return response.Response(
                {"error": "Email is not configured for this PostHog instance."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        params = SendInvitesRequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)

        topic = self.get_object()
        links = _materialize_links_for_topic(topic=topic, team=self.team, created_by=request.user)
        if not links:
            return response.Response(
                {
                    "error": (
                        "Topic has no interviewee_emails or interviewee_distinct_ids set. "
                        "Add them before sending invites."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        topic_label = topic.topic or "a quick research interview"
        subject = params.validated_data.get("subject") or f"Got 5 minutes to talk about {topic_label}?"
        reply_to = params.validated_data.get("reply_to")
        if not reply_to and topic.created_by_id and topic.created_by and topic.created_by.email:
            reply_to = topic.created_by.email
        send_async = params.validated_data["send_async"]

        results: list[dict[str, Any]] = []
        for link in links:
            base = {
                "interviewee_identifier": link["identifier"],
                "email": link["email"],
                "interview_url": link["interview_url"],
            }
            if not link["email"]:
                results.append({**base, "sent": False, "reason": "not_an_email"})
                continue

            campaign_key = f"interview_invite_{link['sharing_configuration'].id}"
            try:
                message = EmailMessage(
                    campaign_key=campaign_key,
                    template_name="interview_invite",
                    subject=subject,
                    template_context={
                        "user_name": link["user_name"],
                        "topic": topic_label,
                        "interview_url": link["interview_url"],
                        "site_url": settings.SITE_URL,
                    },
                    reply_to=reply_to,
                )
                message.add_recipient(email=link["email"], name=link["user_name"])
                message.send(send_async=send_async)
                results.append({**base, "sent": True, "reason": ""})
            except Exception as e:  # noqa: BLE001 — surface per-recipient failures without aborting the batch
                posthoganalytics.capture_exception(e)
                results.append({**base, "sent": False, "reason": f"error:{type(e).__name__}"})

        return response.Response(InterviewInviteResultSerializer(results, many=True).data)


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


@extend_schema(tags=[ProductKey.USER_INTERVIEWS])
class IntervieweeContextViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier)."""

    scope_object = "user_interview"
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
