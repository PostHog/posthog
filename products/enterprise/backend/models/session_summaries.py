from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Optional

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import CreatedMetaFields, UUIDModel

from products.enterprise.backend.hogai.session_summaries.session.output_data import SessionSummarySerializer

if TYPE_CHECKING:
    from products.enterprise.backend.hogai.videos.session_moments import SessionMomentOutput


@dataclass(frozen=True)
class ExtraSummaryContext:
    focus_area: str | None = None


@dataclass(frozen=True)
class SessionSummaryVisualConfirmationResult:
    event_id: str  # Hex id of the event
    event_uuid: str  # Full uuid of the event
    asset_id: int  # Id of the generated video asset
    timestamp_s: int  # Timestamp of starting point in the video
    duration_s: int  # Duration of the video in seconds
    video_description: str  # What LLM found in the video
    created_at: str  # When the video was created, ISO format
    expires_after: str  # When the video will expire, ISO format
    model_id: str  # What model was used to analyze the video

    @classmethod
    def from_session_moment_output(
        cls, session_moment_output: "SessionMomentOutput", event_uuid: str
    ) -> "SessionSummaryVisualConfirmationResult":
        return cls(
            event_id=session_moment_output.moment_id,
            event_uuid=event_uuid,
            asset_id=session_moment_output.asset_id,
            timestamp_s=session_moment_output.timestamp_s,
            duration_s=session_moment_output.duration_s,
            video_description=session_moment_output.video_description,
            created_at=session_moment_output.created_at.isoformat(),
            expires_after=session_moment_output.expires_after.isoformat(),
            model_id=session_moment_output.model_id,
        )


@dataclass(frozen=True)
class SessionSummaryRunMeta:
    """Metadata about the run of the summary generation"""

    model_used: str
    visual_confirmation: bool
    visual_confirmation_results: list[SessionSummaryVisualConfirmationResult] | None = None


@dataclass(frozen=True)
class SessionSummaryPage:
    """Paginated results for session summaries"""

    limit: int
    has_next: bool
    results: list["SingleSessionSummary"]


class SingleSessionSummaryManager(models.Manager["SingleSessionSummary"]):
    """Manager for SingleSessionSummary with utility methods."""

    def get_summary(
        self, team_id: int, session_id: str, *, extra_summary_context: ExtraSummaryContext | None = None
    ) -> Optional["SingleSessionSummary"]:
        """Get a session summary if it exists"""
        queryset = self.filter(team_id=team_id, session_id=session_id)
        # Filter by context presence
        if extra_summary_context is not None:
            # Should have context
            queryset = queryset.filter(extra_summary_context__isnull=False)
        else:
            # No context to match
            queryset = queryset.filter(extra_summary_context__isnull=True)
        summary = queryset.order_by("-created_at").first()
        # No summary found
        if summary is None:
            return None
        # Summary found, no context to match
        if extra_summary_context is None:
            return summary
        # Summary found, context to match
        if summary.extra_summary_context != asdict(extra_summary_context):
            return None
        return summary

    def add_summary(
        self,
        team_id: int,
        session_id: str,
        summary: SessionSummarySerializer,
        exception_event_ids: list[str],
        *,
        extra_summary_context: ExtraSummaryContext | None = None,
        run_metadata: SessionSummaryRunMeta | None = None,
        created_by: User | None = None,
    ) -> None:
        """Store a new session summary"""
        extra_summary_context_dict = asdict(extra_summary_context) if extra_summary_context else None
        run_metadata_dict = asdict(run_metadata) if run_metadata else None
        # No constraints of adding the summary for the same session.
        # It should be impossible, but we get the latest version anyways, even if it happens miracously.
        # I also see value later in storing summaries with/without visual confirmation, different models, etc.
        self.create(
            team_id=team_id,
            session_id=session_id,
            summary=summary.data,
            # Enforce max 100 limit, just in case
            exception_event_ids=exception_event_ids[:100],
            extra_summary_context=extra_summary_context_dict,
            run_metadata=run_metadata_dict,
            created_by=created_by,
        )

    def get_bulk_summaries(
        self,
        team_id: int,
        session_ids: list[str],
        *,
        extra_summary_context: ExtraSummaryContext | None = None,
        # Summaries could be up to 50kb in JSON, so playing it safe
        limit: int = 100,
        offset: int = 0,
    ) -> SessionSummaryPage:
        """Get multiple session summaries with pagination"""
        queryset = self.filter(team_id=team_id, session_id__in=session_ids)
        # Filter by context presence at DB level
        if extra_summary_context is not None:
            # Should have context
            queryset = queryset.filter(extra_summary_context__isnull=False)
        else:
            # No context to match
            queryset = queryset.filter(extra_summary_context__isnull=True)
        # Get the latest summary per session_id with limit+1 to check for more records
        queryset = queryset.order_by("session_id", "-created_at").distinct("session_id")
        # Use Django slicing to SQL LIMIT/OFFSET at the database level
        db_results = list(queryset[offset : offset + limit + 1])
        # Check if there are more records in the database
        has_next = len(db_results) > limit
        # Trim to actual limit
        db_results = db_results[:limit]
        # Filter by the context in Python to ensure the proper match
        if extra_summary_context is not None:
            # Post-filtering could return 0 summaries (if context not matched),
            # but has_next is calculated on DB-level-results, so the pagination would work properly
            extra_summary_context_dict = asdict(extra_summary_context)
            filtered_summaries = [s for s in db_results if s.extra_summary_context == extra_summary_context_dict]
        else:
            filtered_summaries = db_results
        return SessionSummaryPage(
            results=filtered_summaries,
            limit=limit,
            has_next=has_next,
        )

    def summaries_exist(
        self,
        team_id: int,
        session_ids: list[str],
        *,
        extra_summary_context: ExtraSummaryContext | None = None,
    ) -> dict[str, bool]:
        """Check if summaries exist for given session IDs without fetching the full data"""
        result: dict[str, bool] = {session_id: False for session_id in session_ids}
        queryset = self.filter(team_id=team_id, session_id__in=session_ids)
        # Filter by context presence at DB level
        if extra_summary_context is not None:
            # Should have context
            queryset = queryset.filter(extra_summary_context__isnull=False)
        else:
            # No context to match
            queryset = queryset.filter(extra_summary_context__isnull=True)
        # Get the latest summary per session_id, but only fetch minimal data
        queryset = queryset.order_by("session_id", "-created_at").distinct("session_id")
        # Need to fetch context to verify exact match
        if extra_summary_context is not None:
            extra_summary_context_dict = asdict(extra_summary_context)
            existing_summaries = queryset.values_list("session_id", "extra_summary_context")
            for session_id, context in existing_summaries:
                if context == extra_summary_context_dict:
                    result[session_id] = True
        # Simple case - just check existence
        else:
            existing_session_ids = set(queryset.values_list("session_id", flat=True))
            for session_id in existing_session_ids:
                result[session_id] = True
        return result


class SingleSessionSummary(ModelActivityMixin, CreatedMetaFields, UUIDModel):
    """
    Stores LLM-generated session summaries for caching and searching.
    Each summary represents analysis of a single session replay.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    session_id = models.CharField(max_length=200, help_text="Session replay ID")

    # Summary content
    summary = models.JSONField(help_text="Session summary in JSON format (SessionSummarySerializer schema)")

    # Searchable exception events
    exception_event_ids = ArrayField(
        models.CharField(max_length=200),
        default=list,
        blank=True,
        size=100,  # Maximum 100 exception event IDs
        help_text="List of event IDs where exceptions occurred for searchability",
    )

    # Context and metadata
    extra_summary_context = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional context passed to the summary (ExtraSummaryContext schema)",
    )
    run_metadata = models.JSONField(
        null=True,
        blank=True,
        help_text="Summary run metadata (SessionSummaryRunMeta schema)",
    )

    # TODO: Implement background job to delete summaries older than 1 year

    objects = SingleSessionSummaryManager()

    class Meta:
        db_table = "ee_single_session_summary"
        indexes = [
            models.Index(fields=["team", "session_id"]),
            GinIndex(
                name="idx_exception_event_ids_gin",
                fields=["exception_event_ids"],
            ),
        ]

    def __str__(self):
        if self.extra_summary_context:
            return f"Summary for session {self.session_id} with extra context {self.extra_summary_context}"
        return f"Summary for session {self.session_id}"
