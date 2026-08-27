import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field
from rest_framework.exceptions import Throttled

from posthog.api.embedding_worker import async_generate_embedding
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.exceptions import QuotaLimitExceeded
from posthog.models.team import Team
from posthog.models.user import User
from posthog.scopes import APIScopeObject
from posthog.sync import database_sync_to_async, database_sync_to_async_pool

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.replay_vision.backend.api.delivery import archive_delivery, provision_delivery
from products.replay_vision.backend.api.scanners import ReplayScannerSerializer
from products.replay_vision.backend.api.trigger import WorkflowStartOutcome, start_process_vision_action_workflow
from products.replay_vision.backend.api.vision_actions import VisionActionSerializer
from products.replay_vision.backend.billing import CREDITS_PER_DOLLAR, observation_credits_for_model
from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.embeddings import OBSERVATION_EMBEDDING_MODEL
from products.replay_vision.backend.impact import compute_scanner_impact, create_affected_cohort
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_observation_label import ReplayObservationLabel
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import ActionMode, VisionAction, VisionActionRun
from products.replay_vision.backend.observation_formatting import EVENT_ID_CITATION_RE, format_line, read_output
from products.replay_vision.backend.queries.scanner_volume_estimate import (
    ESTIMATE_STALE_AFTER,
    PREVIEW_ESTIMATE_BUDGET,
    estimate_scanner_session_volume,
    project_monthly_observations,
)
from products.replay_vision.backend.quota import compute_quota_snapshot, quota_state
from products.replay_vision.backend.scanner_access import (
    accessible_observations,
    can_read_targeted_experiment,
    is_uuid,
    readable_observation_scanner_ids,
    scanner_for_reading_observations,
    selection_target_ids,
)
from products.replay_vision.backend.scanner_config import scanner_config_error
from products.replay_vision.backend.scanning import (
    MAX_SESSIONS_PER_SCAN,
    RetryOutcome,
    retry_observation,
    run_inline_scan,
    scan_existing_scanner,
)
from products.replay_vision.backend.search import (
    DEFAULT_SEARCH_LIMIT,
    MAX_SEARCH_LIMIT,
    RANK_OVERFETCH_FACTOR,
    ObservationSearchFilters,
    rank_observations,
)
from products.replay_vision.backend.tag_suggestions import suggest_classifier_tags
from products.replay_vision.backend.temporal.metrics import record_scanner_limit_reached

from ee.hogai.tool import MaxTool
from ee.hogai.utils.untrusted import as_untrusted_data, neutralize_markup

logger = structlog.get_logger(__name__)

# Most recent summaries to feed Max — caps the context size for scanners with large histories.
MAX_SUMMARIES = 100


DRAFT_PROMPT_TOOL_DESCRIPTION = """
Use this tool to write or improve the instruction prompt for the Replay Vision scanner the user is
currently configuring, then fill it into their configuration form.

# When to use
- The user is configuring a scanner and asks for help writing, drafting, or improving its prompt
- The user describes what they want a scanner to detect, summarize, classify, or score and wants that turned into a good prompt

# How to write a good scanner prompt
A scanner prompt is the instruction the model follows while watching a single session recording.
Write it as a direct, specific instruction grounded in observable behavior. The shape depends on the scanner type:
- monitor: a yes/no question about whether something happened (e.g. "Did the user fail to complete checkout?").
  State what counts as a yes, and ask for a one-sentence reason.
- classifier: an instruction to categorize the session along one dimension (e.g. by primary user intent).
  Describe the dimension; the tag vocabulary is configured separately, so don't list tags in the prompt.
- scorer: an instruction to rate the session on a single dimension (e.g. frustration).
  Describe what a low score versus a high score means; the numeric scale is configured separately.
- summarizer: an instruction for what the summary should focus on (e.g. the user's goal and the obstacles they hit).

Keep it concrete. Avoid vague adjectives, multi-part questions, and references to data the model cannot
observe in a recording (e.g. revenue, account tier).

# After drafting
Call this tool with the finished prompt — it fills the prompt field in the form the user is editing.
Then briefly explain the choices you made so the user can refine them.
"""


SUMMARIZE_SUMMARIES_TOOL_DESCRIPTION = """
Use this tool to reason across the per-session summaries produced by a Replay Vision *summarizer* scanner.

# When to use
- The user asks for common themes, patterns, or a digest across a summarizer scanner's sessions
- The user asks what users are doing, where they struggle, or what stands out across the summarized recordings
- The user wants a "summary of the summaries"

# What it returns
The scanner's most recent per-session summaries. Synthesize them to answer the user's question —
surface recurring themes, notable outliers, and concrete takeaways rather than restating each summary.
"""


SEARCH_OBSERVATIONS_TOOL_DESCRIPTION = """
Use this tool to find session recordings by the *meaning* of what Replay Vision scanners observed in them —
a semantic search over the model's reasoning, not exact keywords. Each match is a real session recording.

# When to use
- The user asks to find recordings/sessions *where* something happened or *because of* some behavior, bug, or
  theme (e.g. "find recordings where users struggled with checkout", "which sessions got a low score because of
  a broken button?")
- The user wants recordings whose observed reasoning mentions a concept, even if worded differently

# Scope
- Pass a `scanner_id` to search one specific scanner.
- When `scanner_id` is unset, the search defaults to the scanner the user is currently viewing; if they
  aren't on a scanner page it spans every Replay Vision scanner they can read.

Works for every scanner type (monitor, classifier, scorer, summarizer).

# Narrowing by exact result
Combine the semantic `query` with structured filters when the user names a concrete outcome. The filter is
applied first, then the semantic ranking runs only over the matching recordings — so always pass these when
the user states an exact result:
- `verdict` for monitor scanners (e.g. ["yes"] for "recordings that had a YES result because of ...")
- `tags` for classifier scanners (e.g. ["abandoned"] for "sessions classified as abandoned because of ...").
  Pass the tag as the user phrases it — matching is case/format-insensitive (e.g. "Frustrated Or Confused"
  matches the stored `frustrated_or_confused`).
- `min_score` / `max_score` for scorer scanners (e.g. max_score=0 for "scored 0 because of ...")
Put only the meaning in `query` (e.g. "broken checkout button"), and the exact outcome in these filters.

# What it returns
The best-matching observations, ranked by semantic closeness, each with its session (recording) id, the
scanner it came from, verdict/score/tags, and the reasoning snippet. Cite the matching recordings and
synthesize the reasons rather than restating each row.
"""

VALID_SCANNER_TYPES = {t.value for t in ScannerType}


class DraftScannerPromptArgs(BaseModel):
    prompt: str = Field(description="The finished scanner instruction prompt to fill into the configuration form.")
    scanner_type: str | None = Field(
        default=None,
        description="The scanner type the prompt is for (monitor, classifier, scorer, or summarizer). "
        "Only required when not already available from context.",
    )


class ReplayVisionGatesMixin:
    """Shared gates for every Replay Vision tool.

    A plain mixin rather than a MaxTool subclass: `MaxTool.__init_subclass__` requires every subclass to
    carry a `name` registered in `AssistantTool`, so an abstract intermediate isn't expressible. Mixed in
    ahead of MaxTool, its `is_dangerous_operation` still wins the MRO.

    `needs_confirmation` defaults to True on purpose. `MaxTool.is_dangerous_operation` defaults to False, so
    a tool that spends the org's credits and forgets to override it charges them with no confirmation,
    and nothing downstream catches that: scanning.py starts the workflow either way. Inverting the
    default here makes the omission cost a needless prompt instead of a needless charge. Read-only tools
    opt out explicitly, with a reason.

    Spending credits is the usual reason to confirm but not the only one, which is why this isn't named
    after cost: deleting a scanner spends nothing and still asks, because it destroys observations the
    team already paid for.
    """

    needs_confirmation: ClassVar[bool] = True

    # Supplied by MaxTool, which every user of this mixin also inherits. Typed only for the checker:
    # a runtime annotation makes pydantic shadow MaxTool's `user_access_control` cached_property.
    if TYPE_CHECKING:
        _user: User
        _team: Team
        user_access_control: UserAccessControl

    async def is_dangerous_operation(self, **kwargs) -> bool:
        return self.needs_confirmation

    @database_sync_to_async
    def _consent_given(self) -> bool:
        return is_ai_data_processing_approved(self._team.id)

    def _scanner_for(self, scanner_id: str, level: AccessControlLevel = "editor") -> "ReplayScanner | None":
        """A saved scanner this user may act on at `level`.

        Configured only: an inline scan's scanner is a throwaway the reaper may collect, so pointing a
        saved-scanner operation at one would target a row that can vanish underneath it.
        """
        if not is_uuid(scanner_id):
            return None
        scanner = ReplayScanner.objects.filter(team_id=self._team.id, id=scanner_id).first()
        if scanner is None or not self.user_access_control.check_access_level_for_object(scanner, level):
            return None
        return scanner

    def _action_for(self, action_id: str, level: AccessControlLevel = "editor") -> "VisionAction | None":
        """An action this user may act on at `level`.

        Mirrors `_check_action_scanner_access` on the API. The bound scanner is checked at `level`,
        because an action is automation attached to it and a per-scanner restriction has to block it
        here too. Scanners named only in the selection are pure data sources the action never mutates,
        so viewer is the bar for those, but they are checked: a summary fans in their observations and
        its report is derived from all of them.

        The object check on the action itself does not cover either, since `vision_action` inherits the
        `replay_scanner` resource rather than any individual scanner's ACL.
        """
        if not is_uuid(action_id):
            return None
        action = VisionAction.objects.for_team(self._team.id).filter(id=action_id).select_related("scanner").first()
        if action is None or not self.user_access_control.check_access_level_for_object(action, level):
            return None
        if not self.user_access_control.check_access_level_for_object(action.scanner, level):
            return None
        source_ids = selection_target_ids(action.scanner_id, action.selection)
        sources = ReplayScanner.objects.filter(team_id=self._team.id, id__in=source_ids)
        if not all(self.user_access_control.check_access_level_for_object(s, "viewer") for s in sources):
            return None
        return action

    def _observation_for(self, observation_id: str, level: AccessControlLevel = "editor") -> "ReplayObservation | None":
        """An observation this user may act on at `level`. Observations inherit their scanner's RBAC,
        and an experiment scanner's observations also need access to the experiment in their snapshot."""
        if not is_uuid(observation_id):
            return None
        observation = (
            ReplayObservation.objects.filter(team_id=self._team.id, id=observation_id).select_related("scanner").first()
        )
        if observation is None or not self.user_access_control.check_access_level_for_object(
            observation.scanner, level
        ):
            return None
        if not accessible_observations(
            self.user_access_control, self._team.id, ReplayObservation.objects.filter(pk=observation.pk)
        ).exists():
            return None
        return observation

    @staticmethod
    def _no_ai_consent() -> tuple[str, dict[str, Any]]:
        return (
            "This organization hasn't enabled AI analysis of recordings, which Replay Vision needs. "
            "An admin can turn it on in organization settings.",
            {"error": "no_ai_consent"},
        )


class DraftReplayVisionScannerPromptTool(ReplayVisionGatesMixin, MaxTool):
    # Reads and form-fills only; nothing here starts a scan.
    needs_confirmation: ClassVar[bool] = False
    name: str = "draft_replay_vision_scanner_prompt"
    description: str = DRAFT_PROMPT_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = DraftScannerPromptArgs
    context_prompt_template: str = (
        "The user is editing the configuration for a Replay Vision {scanner_type} scanner. "
        "Its current prompt is:\n{current_prompt}"
    )

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        # Drafting writes into the scanner's configuration form, which requires editor access.
        return [("session_recording", "editor")]

    async def _arun_impl(self, prompt: str, scanner_type: str | None = None) -> tuple[str, dict[str, Any]]:
        cleaned = prompt.strip()
        if not cleaned:
            return "No prompt to apply. Please provide the drafted prompt text.", {"error": "empty_prompt"}

        resolved_type = scanner_type or self.context.get("scanner_type")
        # Artifact is consumed by the frontend callback, which fills the prompt field in the form.
        return "Drafted a scanner prompt and filled it into the configuration form.", {
            "prompt": cleaned,
            "scanner_type": resolved_type if resolved_type in VALID_SCANNER_TYPES else None,
        }


class SummarizeSummariesArgs(BaseModel):
    scanner_id: str | None = Field(
        default=None,
        description="The summarizer scanner to digest. Only required when not already available from context.",
    )


class SummarizeReplayVisionSummariesTool(ReplayVisionGatesMixin, MaxTool):
    # Reads and form-fills only; nothing here starts a scan.
    needs_confirmation: ClassVar[bool] = False
    name: str = "summarize_replay_vision_summaries"
    description: str = SUMMARIZE_SUMMARIES_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = SummarizeSummariesArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        # Summaries expose recording content, so reading them requires session_recording access.
        return [("session_recording", "viewer")]

    async def _arun_impl(self, scanner_id: str | None = None) -> tuple[str, dict[str, Any]]:
        resolved_id = self.context.get("scanner_id") or scanner_id
        if not resolved_id:
            return "No scanner specified. Please provide a scanner_id.", {"error": "invalid_context"}

        try:
            return await self._fetch_and_format(str(resolved_id))
        except Exception as e:
            capture_exception(
                e,
                properties={"team_id": self._team.id, "user_id": self._user.id, "scanner_id": str(resolved_id)},
            )
            # Generic content and artifact — the raw exception goes to error tracking above, not the conversation.
            return "Something went wrong loading the summaries. Please try again.", {"error": "fetch_failed"}

    @database_sync_to_async
    def _fetch_and_format(self, scanner_id: str) -> tuple[str, dict[str, Any]]:
        scanner = scanner_for_reading_observations(self._team.id, scanner_id)
        if scanner is None:
            return f"Scanner {scanner_id} not found.", {"error": "not_found"}
        # Summaries inherit the scanner's RBAC — a team member without viewer access to this scanner
        # must not read its recording-derived output. Treat as not-found so we don't leak existence.
        # An experiment scanner also needs access to its targeted experiment.
        if not self.user_access_control.check_access_level_for_object(
            scanner, "viewer"
        ) or not can_read_targeted_experiment(self.user_access_control, self._team.id, scanner):
            return f"Scanner {scanner_id} not found.", {"error": "forbidden"}
        if scanner.scanner_type != ScannerType.SUMMARIZER:
            # Never interpolate the user-editable scanner name into tool output — it's outside the data fence.
            return (
                f"That scanner is a {scanner.scanner_type} scanner, not a summarizer.",
                {"error": "wrong_scanner_type"},
            )

        observations = (
            ReplayObservation.objects.filter(
                team_id=self._team.id, scanner_id=scanner_id, status=ObservationStatus.SUCCEEDED
            )
            .order_by("-created_at")
            .values_list("scanner_result", "created_at")[:MAX_SUMMARIES]
        )

        lines: list[str] = []
        for scanner_result, created_at in observations:
            output = scanner_result.get("model_output") if isinstance(scanner_result, dict) else None
            if not isinstance(output, dict):
                continue
            summary = output.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                continue
            title = output.get("title") if isinstance(output.get("title"), str) else None
            clean = EVENT_ID_CITATION_RE.sub("", summary).strip()
            prefix = f"{created_at:%Y-%m-%d}"
            lines.append(f"- ({prefix}) {f'{title}: ' if title else ''}{clean}")

        if not lines:
            return (
                "This scanner has no completed summaries yet.",
                {"scanner_id": scanner_id, "summary_count": 0},
            )

        header = f"Recent session summaries from this scanner ({len(lines)} of the latest)."
        content = header + "\n\n" + as_untrusted_data("summaries", lines)
        return content, {"scanner_id": scanner_id, "summary_count": len(lines)}


class SearchObservationsArgs(BaseModel):
    query: str = Field(
        max_length=2000,
        description="The natural-language search describing what to find in the recordings' reasoning.",
    )
    scanner_id: str | None = Field(
        default=None,
        description=(
            "Scope the search to a single scanner. When omitted, defaults to the scanner the user is viewing, "
            "or every scanner they can read when not on a scanner page."
        ),
    )
    verdict: list[str] | None = Field(
        default=None,
        description='Keep only monitor results with one of these verdicts (yes, no, inconclusive). e.g. ["yes"].',
    )
    tags: list[str] | None = Field(
        default=None,
        description='Keep only classifier results carrying any of these tags. e.g. ["abandoned"]. '
        "Matching is case/format-insensitive, so pass the tag as the user phrases it.",
    )
    min_score: float | None = Field(
        default=None, description="Keep only scorer results whose score is at least this value."
    )
    max_score: float | None = Field(
        default=None, description="Keep only scorer results whose score is at most this value."
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=MAX_SEARCH_LIMIT,
        description=f"Max number of matching recordings to return (default {DEFAULT_SEARCH_LIMIT}, capped at {MAX_SEARCH_LIMIT}).",
    )


class SearchReplayVisionObservationsTool(ReplayVisionGatesMixin, MaxTool):
    # Reads and form-fills only; nothing here starts a scan.
    needs_confirmation: ClassVar[bool] = False
    name: str = "search_replay_vision_observations"
    description: str = SEARCH_OBSERVATIONS_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = SearchObservationsArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        # Observations expose recording-derived output, so reading them requires session_recording access.
        return [("session_recording", "viewer")]

    async def _arun_impl(
        self,
        query: str,
        scanner_id: str | None = None,
        verdict: list[str] | None = None,
        tags: list[str] | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        limit: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        # Explicit argument wins; scene context is only the default scope when the model passed nothing.
        resolved_id = scanner_id or self.context.get("scanner_id")
        if not query or not query.strip():
            return "No search query provided. Please describe what to look for.", {"error": "empty_query"}

        filters = ObservationSearchFilters.from_raw(verdict, tags, min_score, max_score)
        try:
            return await self._search(str(resolved_id) if resolved_id else None, query.strip(), filters, limit)
        except Exception as e:
            capture_exception(
                e,
                properties={"team_id": self._team.id, "user_id": self._user.id, "scanner_id": str(resolved_id)},
            )
            # Generic content — Max may relay it to the user, so don't surface the raw exception
            # (the full exception is captured to Sentry above).
            return "Something went wrong searching the observations. Please try again.", {"error": "search_failed"}

    async def _search(
        self, scanner_id: str | None, query: str, filters: ObservationSearchFilters, limit: int | None
    ) -> tuple[str, dict[str, Any]]:
        # The embedding call is a 30s-bounded HTTP request; awaiting `async_generate_embedding` lets the event
        # loop schedule other work instead of pinning a Django DB-pool thread for the full network RTT. The DB
        # / ClickHouse pieces stay in `database_sync_to_async` blocks on either side so each thread held is
        # genuinely DB-bound.
        resolved_scope, short_circuit = await self._resolve_search_scope(scanner_id, limit)
        if short_circuit is not None:
            return short_circuit
        assert resolved_scope is not None  # narrows the union; either resolved_scope or short_circuit is non-None
        scanner_ids, scope_label, cross_scanner, capped_limit = resolved_scope

        try:
            embedding_response = await async_generate_embedding(
                self._team, query, model=OBSERVATION_EMBEDDING_MODEL.value
            )
        except Exception:
            logger.warning("replay_vision.observation_search.embedding_failed", team_id=self._team.id, exc_info=True)
            # Could be a timeout, a transport error, or (commonly) the org not having opted into AI data processing.
            return (
                "Couldn't run the search — the embedding service didn't respond. If this persists, check that "
                "the organization has enabled AI data processing (Settings > AI).",
                {"error": "embedding_unavailable"},
            )

        return await self._rank_and_format(
            scanner_ids, scope_label, cross_scanner, capped_limit, query, embedding_response.embedding, filters
        )

    @database_sync_to_async
    def _resolve_search_scope(
        self, scanner_id: str | None, limit: int | None
    ) -> tuple[tuple[list[str], str, bool, int] | None, tuple[str, dict[str, Any]] | None]:
        """Sync gate + scope resolution — runs before the embedding HTTP call. Returns
        `(scope, None)` when search should proceed, or `(None, short_circuit)` when the caller should return
        the short-circuit (content, artifact) tuple as-is. Exactly one half is non-None."""
        scope = self._resolve_scanner_scope(scanner_id)
        if scope is None:
            # `not found` doubles as `no access` so we never leak a scanner's existence.
            return None, (f"Scanner {scanner_id} not found.", {"error": "not_found"})
        scanner_ids, scope_label, cross_scanner = scope
        if not scanner_ids:
            return None, (
                "No Replay Vision scanners are available to search.",
                {"error": "no_scanners", "result_count": 0},
            )

        # Clamp into [1, MAX] so a negative/zero/oversized limit can't reach the ClickHouse LIMIT clause.
        capped_limit = max(1, min(limit or DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT))
        return (scanner_ids, scope_label, cross_scanner, capped_limit), None

    @database_sync_to_async
    def _rank_and_format(
        self,
        scanner_ids: list[str],
        scope_label: str,
        cross_scanner: bool,
        capped_limit: int,
        query: str,
        query_vector: list[float],
        filters: ObservationSearchFilters,
    ) -> tuple[str, dict[str, Any]]:
        """Sync ClickHouse rank + ORM fetch + format — runs after the embedding HTTP call has resolved."""
        empty = (f"No recordings from {scope_label} matched that search yet.", {"result_count": 0})

        # Filter + rank in one ClickHouse query: the structured outcome filters run against the embedding
        # metadata, so the semantic ranking only ever sees recordings that already match the exact outcome.
        # Over-fetch, then cut back down after the loop below drops rows (see RANK_OVERFETCH_FACTOR).
        ordered_ids = [
            match.observation_id
            for match in rank_observations(
                self._team, self._user, scanner_ids, query_vector, capped_limit * RANK_OVERFETCH_FACTOR, filters
            )
        ]
        if not ordered_ids:
            return empty

        observations = {
            str(obs.id): obs
            for obs in accessible_observations(
                self.user_access_control,
                self._team.id,
                ReplayObservation.objects.filter(
                    team_id=self._team.id,
                    scanner_id__in=scanner_ids,
                    status=ObservationStatus.SUCCEEDED,
                    id__in=ordered_ids,
                ),
            )
            .select_related("scanner")
            .only("id", "session_id", "scanner_result", "created_at", "scanner__name")
        }

        lines: list[str] = []
        matched_ids: list[str] = []
        for observation_id in ordered_ids:
            if len(matched_ids) >= capped_limit:
                break
            obs = observations.get(observation_id)
            if obs is None:
                continue
            output = read_output(obs)
            if output is None:
                continue
            lines.append(format_line(obs, output, show_scanner=cross_scanner))
            matched_ids.append(observation_id)

        if not lines:
            return empty

        header = f'Recordings from {scope_label} most relevant to "{neutralize_markup(query)}" ({len(lines)} matches, best first).'
        content = header + "\n\n" + as_untrusted_data("observations", lines)
        return content, {"result_count": len(lines), "observation_ids": matched_ids}

    def _resolve_scanner_scope(self, scanner_id: str | None) -> tuple[list[str], str, bool] | None:
        """Resolve the readable scanner ids for the search. Returns (scanner_ids, label, cross_scanner), or
        None when a specific scanner was requested but is missing/unreadable."""
        if scanner_id:
            try:
                scanner_uuid = uuid.UUID(scanner_id)
            except (ValueError, TypeError):
                # A model-supplied non-UUID would raise ValidationError deeper in the ORM (alert noise); treat as not-found.
                return None
            scanner = scanner_for_reading_observations(self._team.id, scanner_uuid)
            # Observations inherit the scanner's RBAC, and an experiment scanner also needs access to
            # its targeted experiment — treat either miss as not-found.
            if (
                scanner is None
                or not self.user_access_control.check_access_level_for_object(scanner, "viewer")
                or not can_read_targeted_experiment(self.user_access_control, self._team.id, scanner)
            ):
                return None
            # The scanner name is user-editable and the header sits outside the data fence, so keep it out of
            # tool output entirely (stored-injection guard); the searcher already knows which scanner they're on.
            return [str(scanner.id)], "the selected Replay Vision scanner", False
        # Experiment access included, and the experiment lookup batched into one query.
        readable = readable_observation_scanner_ids(self.user_access_control, self._team.id)
        return [str(sid) for sid in readable], "your Replay Vision scanners", True


# Everything a scan costs is priced per observation from this model unless a saved scanner names another.
DEFAULT_SCAN_MODEL = ScannerModel.GEMINI_3_FLASH_PREVIEW

# Pinned to the hour the built-in digest uses, so a summary Max sets up fires at the same time as
# every UI-created one rather than at whatever `starts_at` happened to be.
_SUMMARY_HOUR = 8
# The two cadences worth offering in a chat; anything finer belongs in the UI's rrule editor.
# The scan tool takes no tags or scale, so it offers only the types a prompt alone configures.
_INLINE_SCAN_TYPES = {ScannerType.MONITOR, ScannerType.SUMMARIZER}

_MAX_ACTION_RUNS = 10
# A project can hold hundreds of scanners. The whole list lands in the model's context, so cap it and say so.
_MAX_LISTED = 50
# Free text from a model, so it gets a ceiling before it reaches a column.
MAX_FEEDBACK_LENGTH = 1000

_CADENCE_RRULES = {
    "daily": f"FREQ=DAILY;BYHOUR={_SUMMARY_HOUR};BYMINUTE=0",
    "weekly": f"FREQ=WEEKLY;BYHOUR={_SUMMARY_HOUR};BYMINUTE=0",
}


def _dedup(session_ids: list[str]) -> list[str]:
    """Order-preserving; the same session twice in one batch would just be a wasted no-op."""
    return [s for s in dict.fromkeys(sid.strip() for sid in session_ids) if s]


def _truncate(text: str, limit: int = 120) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "\u2026"


def _credit_sentence(team: Team, cost: int, lead: str = "about") -> str:
    """Credits and dollars against what's left. One phrasing, so a conversation never prices the same
    number two different ways."""
    return _price(cost, quota_state(team.organization_id).remaining, lead)


def _price(cost: int, remaining: int | None, lead: str = "about") -> str:
    priced = f"{lead} {cost} credits (${cost / CREDITS_PER_DOLLAR:,.2f})"
    if remaining is None:
        return f"{priced}. This project has no monthly credit limit set."
    return f"{priced} of the {remaining} left this month."


def _spend_sentence(team: Team, model: str, count: int) -> str:
    """The credit sentence every confirmation prompt ends with.

    Spelled out in credits and dollars against what's left, because the whole point of the confirmation
    is that the user can see what the action costs before it happens.
    """
    return _credit_sentence(team, observation_credits_for_model(model) * count)


def _scan_summary(started: int, results: list[dict[str, str]]) -> str:
    counts: dict[str, int] = {}
    for result in results:
        counts[result["scan_outcome"]] = counts.get(result["scan_outcome"], 0) + 1
    parts = [f"Started {started} scan(s)."]
    if counts.get("already_scanned"):
        parts.append(f"{counts['already_scanned']} already had an answer, reused at no charge.")
    if counts.get("already_running"):
        parts.append(f"{counts['already_running']} were already being scanned.")
    if counts.get("skipped_quota"):
        parts.append(f"{counts['skipped_quota']} were skipped: the monthly credit budget is used up.")
    if counts.get("skipped_scanner_limit"):
        parts.append(
            f"{counts['skipped_scanner_limit']} were skipped: this scanner reached its own credit limit. "
            "Scanning resumes when its billing period resets."
        )
    if counts.get("skipped_limit"):
        parts.append(f"{counts['skipped_limit']} were skipped: too many scans already running.")
    if counts.get("failed"):
        parts.append(f"{counts['failed']} failed to start.")
    if started:
        parts.append("Each recording takes a few minutes. Results appear on the recordings when they finish.")
    return " ".join(parts)


SCAN_SESSIONS_TOOL_DESCRIPTION = """
Use this tool to have Replay Vision watch specific session recordings and answer a question about them.

# When to use
- The user has recordings in hand (from search_session_recordings, from context, or as explicit ids) and
  asks what happened in them, whether something occurred, or to classify or score them
- The user asks to run an existing scanner against particular sessions

# How it works
Each session is scanned by an LLM that watches the recording. Scanning costs credits from the project's
monthly Replay Vision budget, so the user is asked to confirm before anything starts.

Pass `prompt` for a one-off question: nothing is saved and nothing runs on a schedule. Pass `scanner_id`
instead to run a saved scanner over these sessions. Asking the same question twice reuses the answers it
already has rather than charging again.

# What it returns
Confirmation that scans started, and the scan id to read results through. Results are NOT immediate:
each recording takes minutes. Tell the user results will appear on the recordings, and use
search_replay_vision_observations afterwards to read them.
"""


class ScanSessionsArgs(BaseModel):
    session_ids: list[str] = Field(
        description="Session recording ids to scan. Ask the user rather than guessing if you don't have them."
    )
    prompt: str | None = Field(
        default=None,
        description=(
            "What to look for, in plain language, for a one-off question. Leave unset when passing "
            "scanner_id. Write it as a direct instruction grounded in what is observable in a recording."
        ),
    )
    scanner_id: str | None = Field(
        default=None,
        description="Run this saved scanner over the sessions instead of a one-off prompt.",
    )
    scanner_type: str = Field(
        default="monitor",
        description=(
            "For a one-off prompt: 'monitor' for an open-ended yes/no observation (the default), "
            "'summarizer' for a free-text summary. Ignored when scanner_id is set."
        ),
    )


class ScanReplayVisionSessionsTool(ReplayVisionGatesMixin, MaxTool):
    name: str = "scan_replay_vision_sessions"
    description: str = SCAN_SESSIONS_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ScanSessionsArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        # Scanning mints or runs a scanner and spends credits, so it needs the same bar as creating one,
        # plus recording read because the output exposes recording contents.
        return [("replay_scanner", "editor"), ("session_recording", "viewer")]

    async def format_dangerous_operation_preview(
        self, session_ids: list[str], prompt: str | None = None, scanner_id: str | None = None, **kwargs
    ) -> str:
        return await self._preview(_dedup(session_ids), prompt, scanner_id)

    @database_sync_to_async
    def _preview(self, sessions: list[str], prompt: str | None, scanner_id: str | None) -> str:
        """One hop: the scanner lookup and the credit sentence share a connection."""
        model: str = DEFAULT_SCAN_MODEL
        what = f'the question "{_truncate(prompt or "")}"'
        if scanner_id:
            # The same gate the execution path applies. Without it, anyone who can use the tool could
            # pass a scanner id they can't read and see its name and cost in their own approval prompt.
            scanner = self._scanner_for(scanner_id)
            model = scanner.model if scanner else DEFAULT_SCAN_MODEL
            # The scanner name is user-editable, so it stays out of model-visible tool output; this
            # preview is rendered to the user who owns it, not fed back to the model.
            what = f"the saved scanner '{scanner.name}'" if scanner else f"the saved scanner (id {scanner_id})"
        return f"**Scan {len(sessions)} session(s)** with {what}. This spends {_spend_sentence(self._team, model, len(sessions))}"

    async def _arun_impl(
        self,
        session_ids: list[str],
        prompt: str | None = None,
        scanner_id: str | None = None,
        scanner_type: str = "monitor",
    ) -> tuple[str, dict[str, Any]]:
        sessions = _dedup(session_ids)
        if not sessions:
            return "No session ids to scan.", {"error": "no_sessions"}
        if len(sessions) > MAX_SESSIONS_PER_SCAN:
            return (
                f"That's {len(sessions)} recordings; {MAX_SESSIONS_PER_SCAN} is the most one scan can take. "
                "Narrow the selection and try again.",
                {"error": "too_many_sessions"},
            )
        if not await self._consent_given():
            return self._no_ai_consent()
        return await self._start_scan(sessions, prompt, scanner_id, scanner_type)

    @database_sync_to_async
    def _start_scan(
        self, sessions: list[str], prompt: str | None, scanner_id: str | None, scanner_type: str
    ) -> tuple[str, dict[str, Any]]:
        if scanner_id:
            scanner = self._scanner_for(scanner_id)
            if scanner is None:
                return f"Scanner {scanner_id} not found.", {"error": "not_found"}
            started, results = scan_existing_scanner(scanner=scanner, session_ids=sessions, user=self._user)
            if any(result["scan_outcome"] == "skipped_scanner_limit" for result in results):
                record_scanner_limit_reached("max_tool")
            return _scan_summary(started, results), {"scan_id": str(scanner.id), "results": results}

        if not prompt or not prompt.strip():
            return "Pass either a prompt or a scanner_id.", {"error": "no_prompt"}
        # Only the two types whose whole config is a prompt. A classifier or scorer would need tags or
        # a scale, which this tool's schema deliberately doesn't take, and would fail validation with a
        # message about a field the model was never offered.
        resolved_type = scanner_type if scanner_type in _INLINE_SCAN_TYPES else ScannerType.MONITOR
        config = {"prompt": prompt.strip()}
        # Length and shape, through the validator the API uses. This config persists on the scanner and
        # is copied into every observation snapshot, so an unbounded prompt would live on both.
        message = scanner_config_error(ScannerType(resolved_type), config)
        if message is not None:
            return message, {"error": "invalid_config"}
        scan = run_inline_scan(
            team=self._team,
            user=self._user,
            session_ids=sessions,
            scanner_type=ScannerType(resolved_type),
            scanner_config=config,
            model=DEFAULT_SCAN_MODEL,
        )
        if scan.scanner is None:
            return (
                "Nothing started: this project's monthly Replay Vision credits are used up.",
                {"error": "quota_exhausted"},
            )
        return _scan_summary(scan.started, scan.results), {"scan_id": str(scan.scanner.id), "results": scan.results}


QUOTA_TOOL_DESCRIPTION = """
Use this tool to read the project's Replay Vision credit budget for the current billing month.

# When to use
- Before proposing a broad scanner or a large batch of scans, to check what the budget can absorb
- The user asks what Replay Vision has cost, how much budget is left, or why scans are being skipped

# What it returns
Credits used, credits remaining, the monthly limit, when the period resets, and the projected monthly
spend of the scanners already running. Reading this costs nothing.
"""


class ReplayVisionQuotaArgs(BaseModel):
    pass


class GetReplayVisionQuotaTool(ReplayVisionGatesMixin, MaxTool):
    # Reading the budget spends nothing.
    needs_confirmation: ClassVar[bool] = False
    name: str = "get_replay_vision_quota"
    description: str = QUOTA_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ReplayVisionQuotaArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("replay_scanner", "viewer")]

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        return await self._read()

    @database_sync_to_async
    def _read(self) -> tuple[str, dict[str, Any]]:
        snapshot = compute_quota_snapshot(self._team.organization_id)
        resets = snapshot.period_end.strftime("%b %-d")
        if snapshot.credit_limit is None:
            content = (
                f"{snapshot.credits_used} credits used this period, which resets on {resets}. "
                "This project has no monthly credit limit set."
            )
        else:
            content = (
                f"{snapshot.credits_used} of {snapshot.credit_limit} credits used, "
                f"{snapshot.remaining} left. The period resets on {resets}. "
                f"Scanners already running are projected to use {snapshot.projected_monthly_credits} a month."
            )
        return content, {
            "credits_used": snapshot.credits_used,
            "credit_limit": snapshot.credit_limit,
            "credits_remaining": snapshot.remaining,
            "projected_monthly_credits": snapshot.projected_monthly_credits,
            "period_end": snapshot.period_end.isoformat(),
        }


RETRY_OBSERVATION_TOOL_DESCRIPTION = """
Use this tool to scan a recording again after its observation failed or came back ineligible.

# When to use
- The user asks to retry, re-run, or try again on an observation that failed
- A search result shows a failed observation and the user wants another attempt

# What it does
Deletes the failed result and starts a fresh scan of the same recording with the same scanner. This
costs credits like any other scan, so the user is asked to confirm first. Only failed and ineligible
observations can be retried; a succeeded one already has its answer.
"""


class RetryObservationArgs(BaseModel):
    observation_id: str = Field(description="The failed or ineligible observation to scan again.")


class RetryReplayVisionObservationTool(ReplayVisionGatesMixin, MaxTool):
    name: str = "retry_replay_vision_observation"
    description: str = RETRY_OBSERVATION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = RetryObservationArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("replay_scanner", "editor"), ("session_recording", "viewer")]

    async def format_dangerous_operation_preview(self, observation_id: str, **kwargs) -> str:
        return await self._preview(observation_id)

    @database_sync_to_async
    def _preview(self, observation_id: str) -> str:
        """One hop: the observation lookup and the credit sentence share a connection."""
        # Access-checked before anything is rendered: the preview would otherwise disclose the recording
        # id and cost of an observation whose scanner the caller can't read.
        observation = self._observation_for(observation_id)
        if observation is None:
            return f"Retry observation {observation_id}"
        spend = _spend_sentence(self._team, observation.scanner.model, 1)
        return f"**Scan recording {observation.session_id} again**, replacing the failed result. This spends {spend}"

    async def _arun_impl(self, observation_id: str) -> tuple[str, dict[str, Any]]:
        if not await self._consent_given():
            return self._no_ai_consent()
        return await self._retry(observation_id)

    @database_sync_to_async
    def _retry(self, observation_id: str) -> tuple[str, dict[str, Any]]:
        observation = self._observation_for(observation_id)
        if observation is None:
            return f"Observation {observation_id} not found.", {"error": "not_found"}
        try:
            outcome, _ = retry_observation(observation=observation, user=self._user)
        except QuotaLimitExceeded:
            return (
                "Not retried: this project's monthly Replay Vision credits are used up.",
                {"error": "quota_exhausted"},
            )
        except Throttled:
            return (
                "Not retried: too many scans are already running for this project. Try again in a few minutes.",
                {"error": "capped"},
            )
        if outcome is RetryOutcome.NOT_RETRYABLE:
            return (
                "Only failed or ineligible observations can be retried.",
                {"error": "not_retryable"},
            )
        if outcome is RetryOutcome.ALREADY_RUNNING:
            return (
                "The previous run for that recording is still finishing. Try again in a moment.",
                {"error": "already_running"},
            )
        if outcome is RetryOutcome.CAPPED:
            return (
                "Too many scans are already running for this project. Try again in a few minutes.",
                {"error": "capped"},
            )
        if outcome is not RetryOutcome.STARTED:
            return "Couldn't start the retry. Try again in a moment.", {"error": "start_failed"}
        return (
            f"Scanning recording {observation.session_id} again. It takes a few minutes.",
            {"session_id": observation.session_id, "scanner_id": str(observation.scanner_id)},
        )


def _first_error(errors: Any) -> str:
    """The first message out of a DRF error tree, for a chat that has no field to attach it to."""
    if isinstance(errors, dict):
        for value in errors.values():
            return _first_error(value)
    if isinstance(errors, list) and errors:
        return _first_error(errors[0])
    # Neutralized: a uniqueness message echoes a user-editable name straight back into model context.
    return neutralize_markup(str(errors))


def _scanner_config_for(
    scanner_type: ScannerType,
    prompt: str,
    *,
    tags: list[str] | None,
    scale_min: float | None,
    scale_max: float | None,
    length: str | None,
) -> dict[str, Any]:
    """Assemble the per-type config from flat args.

    Flat rather than a nested object because the model fills these in one shot, and a missing piece
    should come back as the validator's own message ("Scale is required.") rather than a schema error.
    Type-specific keys are only included for their type, since the validator rejects unknown ones.
    """
    config: dict[str, Any] = {"prompt": prompt.strip()}
    if scanner_type == ScannerType.CLASSIFIER and tags is not None:
        config["tags"] = tags
    if scanner_type == ScannerType.SCORER and (scale_min is not None or scale_max is not None):
        config["scale"] = {"min": scale_min, "max": scale_max}
    if scanner_type == ScannerType.SUMMARIZER and length is not None:
        config["length"] = length
    return config


CREATE_SCANNER_TOOL_DESCRIPTION = """
Use this tool to create a Replay Vision scanner: a standing watch that scans every future recording
matching a filter.

# When to use
- The user wants recordings that haven't happened yet to be scanned automatically
- The user asks to monitor, track, classify or score sessions on an ongoing basis

# When NOT to use
- The user has recordings in hand and a question about them. That's scan_replay_vision_sessions, which
  saves nothing and schedules nothing. Never create a scanner just to answer one question and delete it.

# Cost
An enabled scanner sweeps every 5 minutes and spends credits on each matching recording, so it can drain
a monthly budget on its own. Creating one enabled asks the user to confirm, with the projected monthly
spend. Create it disabled (`enabled: false`) to set it up without spending anything yet.

Call get_replay_vision_quota first when proposing anything broad, and prefer a `sampling_rate` below 1.0
over an unfiltered scanner.
"""


class CreateScannerArgs(BaseModel):
    name: str = Field(description="Human-readable name, unique within the project.")
    prompt: str = Field(
        description=(
            "The instruction the model follows while watching one recording. Write it as a direct, "
            "specific question grounded in observable behavior, e.g. 'Did the user fail to complete "
            "checkout?'. Avoid vague adjectives and anything the model can't see in a recording."
        )
    )
    scanner_type: str = Field(
        default="monitor",
        description=(
            "What each observation produces: 'monitor' for a yes/no answer with a reason, 'classifier' "
            "to assign tags from a fixed vocabulary, 'scorer' for a number on a scale, 'summarizer' for "
            "a free-text summary."
        ),
    )
    tags: list[str] | None = Field(
        default=None,
        description=(
            "Classifiers only, and required for them: the fixed vocabulary the model picks from, e.g. "
            "['abandoned cart', 'payment error', 'browsing']. Cover the outcomes the user cares about "
            "and keep them distinguishable from each other."
        ),
    )
    scale_min: float | None = Field(
        default=None,
        description="Scorers only, and required for them: the low end of the scale, e.g. 0.",
    )
    scale_max: float | None = Field(
        default=None,
        description="Scorers only, and required for them: the high end of the scale, e.g. 5.",
    )
    length: str | None = Field(
        default=None,
        description="Summarizers only, optional: 'short', 'medium' (the default) or 'long'.",
    )
    sampling_rate: float = Field(
        default=1.0,
        description="Fraction of matching recordings to scan, 0 to 1. Lower this to control spend.",
    )
    enabled: bool = Field(
        default=False,
        description=(
            "Leave false to create it without starting the sweep, which spends nothing. Set true only "
            "when the user has agreed to the recurring cost."
        ),
    )


class CreateReplayVisionScannerTool(ReplayVisionGatesMixin, MaxTool):
    name: str = "create_replay_vision_scanner"
    description: str = CREATE_SCANNER_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = CreateScannerArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("replay_scanner", "editor"), ("session_recording", "viewer")]

    async def is_dangerous_operation(self, enabled: bool = False, **kwargs) -> bool:
        # Argument-dependent, so the mixin's `needs_confirmation` doesn't decide it: a disabled scanner has
        # no schedule and spends nothing, and only an enabled one needs a decision.
        return enabled is True

    async def format_dangerous_operation_preview(self, name: str = "", sampling_rate: float = 1.0, **kwargs) -> str:
        return await self._preview(name, sampling_rate)

    @database_sync_to_async
    def _preview(self, name: str, sampling_rate: float) -> str:
        spend = _spend_sentence(self._team, DEFAULT_SCAN_MODEL, 1)
        sampled = "" if sampling_rate >= 1.0 else f" It samples {sampling_rate:.0%} of them."
        return (
            f"**Create and enable** scanner '{name}'. It scans every new recording from now on, "
            f"sweeping every 5 minutes.{sampled} Each recording costs {spend} "
            "Create it disabled instead if you want to size it first."
        )

    async def _arun_impl(
        self,
        name: str,
        prompt: str,
        scanner_type: str = "monitor",
        sampling_rate: float = 1.0,
        enabled: bool = False,
        tags: list[str] | None = None,
        scale_min: float | None = None,
        scale_max: float | None = None,
        length: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        # Not gated on `enabled`: the serializer refuses to create either kind without consent, so
        # checking only for enabled ones turned the disabled path into an unhandled exception.
        if not await self._consent_given():
            return self._no_ai_consent()
        return await self._create(
            name, prompt, scanner_type, sampling_rate, enabled, tags, scale_min, scale_max, length
        )

    @database_sync_to_async
    def _create(
        self,
        name: str,
        prompt: str,
        scanner_type: str,
        sampling_rate: float,
        enabled: bool,
        tags: list[str] | None,
        scale_min: float | None,
        scale_max: float | None,
        length: str | None,
    ) -> tuple[str, dict[str, Any]]:
        resolved_type = scanner_type if scanner_type in VALID_SCANNER_TYPES else ScannerType.MONITOR
        # Through the serializer, not ReplayScanner.objects.create: it owns the sampling-rate floor below
        # which a scanner silently never scans, the unique-name race, the estimate refresh, the built-in
        # featured digest, and the lifecycle event. A scanner Max makes should be the same object the UI makes.
        serializer = ReplayScannerSerializer(
            data={
                "name": name.strip(),
                "scanner_type": resolved_type,
                "scanner_config": _scanner_config_for(
                    ScannerType(resolved_type),
                    prompt,
                    tags=tags,
                    scale_min=scale_min,
                    scale_max=scale_max,
                    length=length,
                ),
                "model": DEFAULT_SCAN_MODEL,
                "sampling_rate": sampling_rate,
                "enabled": enabled,
            },
            context={"get_team": lambda: self._team, "user": self._user},
        )
        if not serializer.is_valid():
            return _first_error(serializer.errors), {"error": "invalid_config"}
        scanner = serializer.save()
        state = (
            "It's running and will scan new recordings as they arrive."
            if enabled
            else "It's turned off for now, so it isn't scanning or spending anything. Enable it when you're ready."
        )
        # The name stays out of `content`, which the model reads: it's user-editable from here on, and
        # the file's own rule keeps it outside the data fence. The artifact goes to the frontend.
        return f"Created the {resolved_type} scanner. {state}", {
            "scanner_name": scanner.name,
            "scanner_id": str(scanner.id),
            "enabled": enabled,
        }


CREATE_ACTION_TOOL_DESCRIPTION = """
Use this tool to set up a recurring summary of what a Replay Vision scanner is finding.

# When to use
- The user wants a daily or weekly digest of a scanner's observations
- The user asks to be kept updated on what a scanner is seeing, without reading each observation

# What it does
Creates a scheduled group summary: on the cadence you give it, one report is synthesized from the
observations the scanner produced since the last run. It starts no new scans, so it spends no Replay
Vision credits, but each run calls the synthesis model and bills the team's AI credits. That recurs
until someone disables it, so the user is asked to confirm before it is created.

The report appears in the app. Delivering it to Slack or a webhook needs an integration id, so point the
user at the scanner's "Summaries and alerts" tab for that rather than guessing one.

For an alert that fires on a condition rather than a cadence, point the user at that tab too: alerts need
a threshold, a metric and a window that are easier to set there.
"""


class CreateVisionActionArgs(BaseModel):
    scanner_id: str = Field(description="The scanner whose observations get summarized.")
    name: str = Field(description="Human-readable name, unique within the project.")
    cadence: str = Field(
        default="daily",
        description="How often the summary runs: 'daily' or 'weekly'.",
    )
    focus: str | None = Field(
        default=None,
        description="Optional steer on what the summary should emphasize, e.g. 'group by the feature involved'.",
    )


class CreateReplayVisionActionTool(ReplayVisionGatesMixin, MaxTool):
    # It spends no Replay Vision observation credits, but each run calls the synthesis model with
    # `$ai_billable`, so it commits the team to recurring AI spend that continues until someone disables
    # it. Recurring, agent-created spend is the case the confirmation exists for.
    needs_confirmation: ClassVar[bool] = True
    name: str = "create_replay_vision_action"
    description: str = CREATE_ACTION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = CreateVisionActionArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("vision_action", "editor"), ("session_recording", "viewer")]

    async def format_dangerous_operation_preview(self, name: str = "", cadence: str = "daily", **kwargs) -> str:
        return (
            f"**Create a {cadence} summary** '{name}'. It runs on that schedule from now on, and each run "
            "calls the synthesis model and bills the project's AI credits. It keeps running until someone "
            "disables it. This spends no Replay Vision scanning credits."
        )

    async def _arun_impl(
        self, scanner_id: str, name: str, cadence: str = "daily", focus: str | None = None
    ) -> tuple[str, dict[str, Any]]:
        return await self._create(scanner_id, name, cadence, focus)

    @database_sync_to_async
    def _create(self, scanner_id: str, name: str, cadence: str, focus: str | None) -> tuple[str, dict[str, Any]]:
        rrule = _CADENCE_RRULES.get(cadence.strip().lower())
        if rrule is None:
            return "Cadence has to be 'daily' or 'weekly'.", {"error": "invalid_cadence"}
        # Configured scanners only: a summary is a standing job, and an inline scan's scanner is a
        # throwaway the reaper may collect.
        scanner = (
            ReplayScanner.objects.filter(team_id=self._team.id, id=scanner_id).first() if is_uuid(scanner_id) else None
        )
        # Editor, not viewer: an action is automation bound to the scanner, and _check_action_scanner_access
        # object-checks the target at editor level for writes. Viewer here would let a per-scanner
        # restriction that blocks the API be walked around through Max.
        if scanner is None or not self.user_access_control.check_access_level_for_object(scanner, "editor"):
            return f"Scanner {scanner_id} not found.", {"error": "not_found"}
        # Through the serializer so the rrule and timezone are validated and the unique-name race is
        # handled, rather than writing a trigger_config the scheduler later chokes on.
        serializer = VisionActionSerializer(
            data={
                "name": name.strip(),
                "scanner": str(scanner.id),
                "mode": ActionMode.GROUP_SUMMARY,
                "trigger_config": {"rrule": rrule, "timezone": self._team.timezone or "UTC"},
                "synthesis_config": {"prompt_guide": focus.strip()} if focus and focus.strip() else {},
            },
            # team_id is not optional: the scanner field is team-scoped and fails safe to .none(),
            # so without it the scanner never resolves and every call fails validation.
            context={"get_team": lambda: self._team, "team_id": self._team.id, "user": self._user},
        )
        if not serializer.is_valid():
            return _first_error(serializer.errors), {"error": "invalid_config"}
        action = serializer.save()
        return (
            f"Created a {cadence} summary of that scanner's observations. It appears on the scanner's "
            "'Summaries and alerts' tab, and you can add Slack or webhook delivery there.",
            {"vision_action_id": str(action.id)},
        )


def _monthly_spend_sentence(team: Team, scanner: ReplayScanner, sampling_rate: float) -> str:
    """Projected monthly cost of running a scanner, which is what enabling actually commits to.

    A per-recording price understates a schedule. The estimate is the same number the UI shows before
    saving; when it hasn't been computed yet, say so rather than imply a small one-off charge.
    """
    observations = scanner.estimated_monthly_observations
    stale = scanner.estimated_at is None or timezone.now() - scanner.estimated_at >= ESTIMATE_STALE_AFTER
    if observations is None or stale:
        return "Its monthly volume hasn't been estimated recently, so the cost isn't known up front."
    # The stored estimate is for the scanner's saved rate; rescale when the rate is changing.
    if scanner.sampling_rate:
        observations = round(observations * sampling_rate / scanner.sampling_rate)
    cost = observation_credits_for_model(scanner.model) * observations
    priced = _credit_sentence(team, cost, lead=f"about {observations} recordings a month,")
    return f"That's {priced}"


UPDATE_SCANNER_TOOL_DESCRIPTION = """
Use this tool to change a saved Replay Vision scanner: turn it on or off, rename it, reword its prompt,
or change how much of the matching traffic it samples.

# When to use
- The user wants to enable a scanner they created earlier, or pause one that's running
- The user wants to reword what a scanner looks for, or dial its sampling up or down

# Cost
Enabling a scanner starts a sweep that runs every 5 minutes and spends credits on each matching
recording, so enabling asks the user to confirm and shows the projected monthly spend. Raising the
sampling rate on a scanner that is already running does the same, because it widens what gets scanned.
Turning a scanner off, renaming it, or rewording its prompt spends nothing and doesn't ask.

Rewording the prompt does not rescan anything already observed; it applies to recordings scanned from
then on.
"""


class UpdateScannerArgs(BaseModel):
    scanner_id: str = Field(description="The scanner to change.")
    enabled: bool | None = Field(
        default=None,
        description="True to start its schedule, false to pause it. Leave unset to keep it as it is.",
    )
    name: str | None = Field(default=None, description="New name. Leave unset to keep the current one.")
    prompt: str | None = Field(
        default=None,
        description="New instruction for the scanner. Leave unset to keep the current one.",
    )
    sampling_rate: float | None = Field(
        default=None,
        description="New fraction of matching recordings to scan, 0 to 1. Leave unset to keep the current one.",
    )


class UpdateReplayVisionScannerTool(ReplayVisionGatesMixin, MaxTool):
    name: str = "update_replay_vision_scanner"
    description: str = UPDATE_SCANNER_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = UpdateScannerArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("replay_scanner", "editor"), ("session_recording", "viewer")]

    async def is_dangerous_operation(
        self, scanner_id: str = "", enabled: bool | None = None, sampling_rate: float | None = None, **kwargs
    ) -> bool:
        # Argument-dependent, so the mixin's `needs_confirmation` doesn't decide it. Only two edits commit
        # the project to spend: starting the schedule, and widening what a running schedule scans.
        # Pausing, renaming and rewording all cost nothing.
        return await self._starts_or_widens_spending(scanner_id, enabled, sampling_rate)

    @database_sync_to_async
    def _starts_or_widens_spending(self, scanner_id: str, enabled: bool | None, sampling_rate: float | None) -> bool:
        if enabled is True:
            return True
        scanner = self._scanner_for(scanner_id)
        if scanner is None or enabled is False:
            return False
        return sampling_rate is not None and scanner.enabled and sampling_rate > scanner.sampling_rate

    async def format_dangerous_operation_preview(
        self, scanner_id: str = "", enabled: bool | None = None, sampling_rate: float | None = None, **kwargs
    ) -> str:
        return await self._preview(scanner_id, enabled, sampling_rate)

    @database_sync_to_async
    def _preview(self, scanner_id: str, enabled: bool | None, sampling_rate: float | None) -> str:
        scanner = self._scanner_for(scanner_id)
        if scanner is None:
            return f"Update scanner {scanner_id}"
        rate = sampling_rate if sampling_rate is not None else scanner.sampling_rate
        action = "**Turn on**" if enabled is True else "**Widen**"
        return (
            f"{action} scanner '{scanner.name}'. It sweeps every 5 minutes, scanning "
            f"{rate:.0%} of matching recordings, and keeps spending until it's turned off. "
            f"{_monthly_spend_sentence(self._team, scanner, rate)}"
        )

    async def _arun_impl(
        self,
        scanner_id: str,
        enabled: bool | None = None,
        name: str | None = None,
        prompt: str | None = None,
        sampling_rate: float | None = None,
    ) -> tuple[str, dict[str, Any]]:
        # The serializer refuses to enable without consent, so answer rather than raise.
        if enabled is True and not await self._consent_given():
            return self._no_ai_consent()
        return await self._update(scanner_id, enabled, name, prompt, sampling_rate)

    @database_sync_to_async
    def _update(
        self,
        scanner_id: str,
        enabled: bool | None,
        name: str | None,
        prompt: str | None,
        sampling_rate: float | None,
    ) -> tuple[str, dict[str, Any]]:
        scanner = self._scanner_for(scanner_id)
        if scanner is None:
            return f"Scanner {scanner_id} not found.", {"error": "not_found"}
        data: dict[str, Any] = {}
        if enabled is not None:
            data["enabled"] = enabled
        if name is not None:
            data["name"] = name.strip()
        if sampling_rate is not None:
            data["sampling_rate"] = sampling_rate
        if prompt is not None:
            # Merged, not replaced: the rest of the config (tags, scale, length) belongs to its type.
            data["scanner_config"] = {**scanner.scanner_config, "prompt": prompt.strip()}
        if not data:
            return "Nothing to change. Say what you want to update.", {"error": "no_changes"}
        # Through the serializer so the sampling floor, the unique-name race, the estimate refresh on
        # enable and the version bump all hold, exactly as they do for a UI edit.
        serializer = ReplayScannerSerializer(
            scanner,
            data=data,
            partial=True,
            context={"get_team": lambda: self._team, "user": self._user},
        )
        if not serializer.is_valid():
            return _first_error(serializer.errors), {"error": "invalid_config"}
        updated = serializer.save()
        state = "It's running now." if updated.enabled else "It's turned off, so it isn't scanning or spending."
        return f"Updated the scanner. {state}", {
            "scanner_id": str(updated.id),
            "enabled": updated.enabled,
            "changed": sorted(data),
        }


LIST_SCANNERS_TOOL_DESCRIPTION = """
Use this tool to see the Replay Vision scanners in the project, and to turn a scanner the user names
into the id every other Replay Vision tool needs.

# When to use
- The user refers to a scanner by name ("turn on my checkout scanner") and you don't have its id
- The user asks what scanners exist, which are running, or what they're each watching
- Before creating a scanner, to check whether one already covers the same question

# What it returns
Each scanner's id, name, type, whether it's running, its sampling rate, and its estimated monthly
volume where one has been computed. Reading this costs nothing.
"""


class ListScannersArgs(BaseModel):
    enabled_only: bool = Field(
        default=False,
        description="Only scanners currently running. Leave false to see paused ones too.",
    )


class ListReplayVisionScannersTool(ReplayVisionGatesMixin, MaxTool):
    # Reading the list spends nothing.
    needs_confirmation: ClassVar[bool] = False
    name: str = "list_replay_vision_scanners"
    description: str = LIST_SCANNERS_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ListScannersArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("replay_scanner", "viewer")]

    async def _arun_impl(self, enabled_only: bool = False) -> tuple[str, dict[str, Any]]:
        return await self._list(enabled_only)

    @database_sync_to_async
    def _list(self, enabled_only: bool) -> tuple[str, dict[str, Any]]:
        # Configured only, and RBAC-filtered like the scanner list endpoint: inline scans are throwaways
        # and a scanner the caller can't read shouldn't be nameable here.
        queryset = ReplayScanner.objects.filter(team_id=self._team.id)
        if enabled_only:
            queryset = queryset.filter(enabled=True)
        readable = self.user_access_control.filter_queryset_by_access_level(queryset).order_by("name", "id")
        scanners = [
            {
                "scanner_id": str(s.id),
                # Names are user-editable, so they go back as untrusted data rather than as prose the
                # model reads as its own instruction.
                "name": neutralize_markup(s.name),
                "scanner_type": s.scanner_type,
                "enabled": s.enabled,
                "sampling_rate": s.sampling_rate,
                "estimated_monthly_observations": s.estimated_monthly_observations,
            }
            for s in readable[:_MAX_LISTED]
        ]
        if not scanners:
            return "This project has no Replay Vision scanners yet.", {"scanners": []}
        total = readable.count()
        running = sum(1 for s in scanners if s["enabled"])
        shown = f"{len(scanners)} of {total} scanner(s)" if total > len(scanners) else f"{len(scanners)} scanner(s)"
        return (
            f"{shown}, {running} of those running. Their ids are in the result, for use with the "
            "other Replay Vision tools.",
            {"scanners": scanners, "total": total},
        )


DELETE_SCANNER_TOOL_DESCRIPTION = """
Use this tool to delete a Replay Vision scanner.

# When to use
- The user explicitly asks to delete or remove a scanner

# What it does
Deletes the scanner and every observation it ever produced. That history is not recoverable, and the
usage already billed for those scans is not refunded. Pausing is almost always what someone wants
instead, so offer update_replay_vision_scanner with enabled false first, and only delete when the user
is clear that's what they mean. The user is asked to confirm, and the prompt says how many observations
will go with it.
"""


class DeleteScannerArgs(BaseModel):
    scanner_id: str = Field(description="The scanner to delete, along with all of its observations.")


class DeleteReplayVisionScannerTool(ReplayVisionGatesMixin, MaxTool):
    # Spends nothing, but destroys history irreversibly, which is its own reason to ask.
    needs_confirmation: ClassVar[bool] = True
    name: str = "delete_replay_vision_scanner"
    description: str = DELETE_SCANNER_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = DeleteScannerArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("replay_scanner", "editor")]

    async def format_dangerous_operation_preview(self, scanner_id: str = "", **kwargs) -> str:
        return await self._preview(scanner_id)

    @database_sync_to_async
    def _preview(self, scanner_id: str) -> str:
        scanner = self._scanner_for(scanner_id)
        if scanner is None:
            return f"Delete scanner {scanner_id}"
        observations = ReplayObservation.objects.filter(team_id=self._team.id, scanner_id=scanner.id).count()
        return (
            f"**Delete** scanner '{scanner.name}' and its {observations} observation(s). The results are "
            "gone for good and the credits already spent on them aren't refunded. Pausing it instead "
            "keeps the history."
        )

    async def _arun_impl(self, scanner_id: str) -> tuple[str, dict[str, Any]]:
        return await self._delete(scanner_id)

    @database_sync_to_async
    def _delete(self, scanner_id: str) -> tuple[str, dict[str, Any]]:
        scanner = self._scanner_for(scanner_id)
        if scanner is None:
            return f"Scanner {scanner_id} not found.", {"error": "not_found"}
        name, deleted_id = scanner.name, str(scanner.id)
        scanner.delete()
        return "Deleted the scanner and its observations.", {"scanner_id": deleted_id, "name": name}


ESTIMATE_SCANNER_TOOL_DESCRIPTION = """
Use this tool to find out how many recordings a scanner would scan each month, and what that would
cost, before creating or enabling one.

# When to use
- Before creating a scanner, especially a broad one, so the user can see the monthly spend first
- Before enabling a scanner the user created earlier
- The user asks how expensive a scanner would be, or how much traffic it would cover

# What it returns
Projected recordings a month, the credits that costs, and what's left in the monthly budget. Estimating
costs nothing and scans nothing.

Pass `scanner_id` to size a scanner that already exists. Pass `sampling_rate` on its own to see what a
different rate would cost.
"""


class EstimateScannerArgs(BaseModel):
    scanner_id: str = Field(description="The scanner to size.")
    sampling_rate: float | None = Field(
        default=None,
        description="Try a different fraction of matching recordings, 0 to 1. Leave unset to use the scanner's own.",
    )


class EstimateReplayVisionScannerTool(ReplayVisionGatesMixin, MaxTool):
    # Counts candidate sessions; scans nothing.
    needs_confirmation: ClassVar[bool] = False
    name: str = "estimate_replay_vision_scanner"
    description: str = ESTIMATE_SCANNER_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = EstimateScannerArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        # The candidate query runs over recording data, so a probed filter could leak recording metadata.
        return [("replay_scanner", "viewer"), ("session_recording", "viewer")]

    async def _arun_impl(self, scanner_id: str, sampling_rate: float | None = None) -> tuple[str, dict[str, Any]]:
        return await self._estimate(scanner_id, sampling_rate)

    def _cached_projection(self, scanner: ReplayScanner, rate: float) -> int | None:
        """The stored estimate, when it's still good for this scanner.

        `ReplayScanner.save` clears `estimated_at` whenever a volume input changes, so a fresh timestamp
        means the number still matches the config. Rescaling by rate keeps a model iterating on sampling
        off ClickHouse entirely, which is the common case for this tool.
        """
        if scanner.estimated_at is None or scanner.estimated_monthly_observations is None:
            return None
        if timezone.now() - scanner.estimated_at >= ESTIMATE_STALE_AFTER:
            return None
        if not scanner.sampling_rate:
            return None
        return round(scanner.estimated_monthly_observations * rate / scanner.sampling_rate)

    @database_sync_to_async
    def _estimate(self, scanner_id: str, sampling_rate: float | None) -> tuple[str, dict[str, Any]]:
        scanner = self._scanner_for(scanner_id, "viewer")
        if scanner is None:
            return f"Scanner {scanner_id} not found.", {"error": "not_found"}
        rate = scanner.sampling_rate if sampling_rate is None else sampling_rate
        if not 0.0 <= rate <= 1.0:
            return "Sampling rate has to be between 0 and 1.", {"error": "invalid_sampling_rate"}
        observations = self._cached_projection(scanner, rate)
        if observations is None:
            try:
                estimate = estimate_scanner_session_volume(
                    team=self._team,
                    query=scanner.targeted_recordings_query(),
                    # The exposure filter's access check runs as whoever is asking Max.
                    user=self._user,
                    sampling_mode=scanner.sampling_mode,
                    ch_user=ClickHouseUser.REPLAY_VISION,
                    budget=PREVIEW_ESTIMATE_BUDGET,
                )
            except Exception:
                logger.exception("replay_vision.max_tools.estimate_failed", scanner_id=scanner_id)
                return "Couldn't work out the volume for that scanner just now.", {"error": "estimate_failed"}
            observations = project_monthly_observations(estimate, rate)
        cost = observation_credits_for_model(scanner.model) * observations
        remaining = quota_state(self._team.organization_id).remaining
        return (
            f"About {observations} recordings a month at {rate:.0%} sampling, costing roughly "
            f"{_price(cost, remaining, lead='')}".strip(),
            {
                "estimated_monthly_observations": observations,
                "estimated_monthly_credits": cost,
                "sampling_rate": rate,
                "credits_remaining": remaining,
            },
        )


READ_ACTIONS_TOOL_DESCRIPTION = """
Use this tool to see the recurring summaries and alerts set up over Replay Vision scanners, and to read
the reports they've produced.

# When to use
- The user asks what summaries or alerts exist, or which are running
- The user asks what the latest summary said, or what a digest found
- You need an action's id for update, run, or delete

# What it returns
With no `action_id`, every action with its id, name, mode, cadence and whether it's enabled. With an
`action_id`, that action's recent runs and their synthesized reports. Reading costs nothing.
"""


class ReadActionsArgs(BaseModel):
    action_id: str | None = Field(
        default=None,
        description="Read this action's recent runs and their reports. Leave unset to list every action.",
    )


class ReadReplayVisionActionsTool(ReplayVisionGatesMixin, MaxTool):
    # Reading spends nothing.
    needs_confirmation: ClassVar[bool] = False
    name: str = "read_replay_vision_actions"
    description: str = READ_ACTIONS_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ReadActionsArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        # Reports quote recording-derived output, so reading them needs recording read.
        return [("vision_action", "viewer"), ("session_recording", "viewer")]

    async def _arun_impl(self, action_id: str | None = None) -> tuple[str, dict[str, Any]]:
        return await self._read(action_id)

    @database_sync_to_async
    def _read(self, action_id: str | None) -> tuple[str, dict[str, Any]]:
        if action_id is None:
            readable = self._readable_actions().order_by("name", "id")
            actions = [
                {
                    "action_id": str(a.id),
                    # User-editable, so it goes back neutralized rather than as prose the model trusts.
                    "name": neutralize_markup(a.name),
                    "mode": a.mode,
                    "enabled": a.enabled,
                    "rrule": (a.trigger_config or {}).get("rrule"),
                    "scanner_id": str(a.scanner_id),
                }
                for a in readable[:_MAX_LISTED]
            ]
            if not actions:
                return "This project has no Replay Vision summaries or alerts yet.", {"actions": []}
            total = readable.count()
            shown = f"{len(actions)} of {total} action(s)" if total > len(actions) else f"{len(actions)} action(s)"
            return f"{shown}. Their ids are in the result.", {"actions": actions, "total": total}

        action = self._action_for(action_id, "viewer")
        if action is None:
            return f"Action {action_id} not found.", {"error": "not_found"}
        runs = [
            {
                "run_id": str(r.id),
                "status": r.status,
                "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
                "observation_count": r.observation_count,
                # The report is model-written over recording content, so it stays fenced.
                "report": as_untrusted_data("report", [r.synthesized_markdown]) if r.synthesized_markdown else None,
            }
            for r in VisionActionRun.objects.for_team(self._team.id)
            .filter(vision_action_id=action.id)
            .order_by("-scheduled_at")[:_MAX_ACTION_RUNS]
            if self._may_read_run(r)
        ]
        if not runs:
            return "That action hasn't run yet.", {"action_id": action_id, "runs": []}
        return f"The {len(runs)} most recent run(s) for that action.", {"action_id": action_id, "runs": runs}

    def _may_read_run(self, run: VisionActionRun) -> bool:
        """Whether this user may read the report a past run produced.

        A run's `observation_ids` reflect the selection at run time, so a later selection edit, or a
        grant revoked since, can leave the report drawing on a scanner the caller can't read. Same check
        `VisionActionRunViewSet.retrieve` applies; viewer is the bar, as these are read-only sources.
        """
        ids = run.observation_ids if isinstance(run.observation_ids, list) else []
        if not ids:
            return True
        scanner_ids = set(
            ReplayObservation.objects.filter(team_id=self._team.id, id__in=ids).values_list("scanner_id", flat=True)
        )
        scanners = ReplayScanner.objects.filter(team_id=self._team.id, id__in=scanner_ids)
        return all(self.user_access_control.check_access_level_for_object(s, "viewer") for s in scanners)

    def _readable_actions(self) -> "QuerySet[VisionAction]":
        """Actions whose bound scanner this user may read.

        The resource-level filter isn't enough alone: `vision_action` inherits the `replay_scanner`
        resource, not any individual scanner's ACL, so a per-scanner restriction would still leave the
        action listed along with reports derived from that scanner's observations.
        """
        actions = self.user_access_control.filter_queryset_by_access_level(VisionAction.objects.for_team(self._team.id))
        readable_scanners = self.user_access_control.filter_queryset_by_access_level(
            ReplayScanner.objects.filter(team_id=self._team.id)
        )
        return actions.filter(scanner_id__in=readable_scanners.values("id"))


UPDATE_ACTION_TOOL_DESCRIPTION = """
Use this tool to change a recurring Replay Vision summary or alert: pause it, resume it, rename it, or
change how often it runs.

# When to use
- The user wants to stop a summary that keeps arriving, or start one again
- The user wants a daily digest weekly, or the other way round

# Cost
Resuming an action means each run calls the synthesis model and bills the project's AI credits, on that
cadence, until it's paused again, so resuming asks the user to confirm. Pausing and renaming cost
nothing.
"""


class UpdateActionArgs(BaseModel):
    action_id: str = Field(description="The summary or alert to change.")
    enabled: bool | None = Field(
        default=None, description="False to pause it, true to resume. Leave unset to keep it as it is."
    )
    name: str | None = Field(default=None, description="New name. Leave unset to keep the current one.")
    cadence: str | None = Field(
        default=None, description="New cadence: 'daily' or 'weekly'. Leave unset to keep the current one."
    )


class UpdateReplayVisionActionTool(ReplayVisionGatesMixin, MaxTool):
    name: str = "update_replay_vision_action"
    description: str = UPDATE_ACTION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = UpdateActionArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("vision_action", "editor"), ("session_recording", "viewer")]

    async def is_dangerous_operation(self, enabled: bool | None = None, **kwargs) -> bool:
        # Argument-dependent: resuming restarts recurring AI spend, pausing and renaming stop or cost nothing.
        return enabled is True

    async def format_dangerous_operation_preview(self, action_id: str = "", **kwargs) -> str:
        return (
            f"**Resume** summary {action_id}. Each run calls the synthesis model and bills the project's "
            "AI credits, on its schedule, until it's paused again."
        )

    async def _arun_impl(
        self, action_id: str, enabled: bool | None = None, name: str | None = None, cadence: str | None = None
    ) -> tuple[str, dict[str, Any]]:
        return await self._update(action_id, enabled, name, cadence)

    @database_sync_to_async
    def _update(
        self, action_id: str, enabled: bool | None, name: str | None, cadence: str | None
    ) -> tuple[str, dict[str, Any]]:
        action = self._action_for(action_id)
        if action is None:
            return f"Action {action_id} not found.", {"error": "not_found"}
        data: dict[str, Any] = {}
        if enabled is not None:
            data["enabled"] = enabled
        if name is not None:
            data["name"] = name.strip()
        if cadence is not None:
            rrule = _CADENCE_RRULES.get(cadence.strip().lower())
            if rrule is None:
                return "Cadence has to be 'daily' or 'weekly'.", {"error": "invalid_cadence"}
            data["trigger_config"] = {**(action.trigger_config or {}), "rrule": rrule}
        if not data:
            return "Nothing to change. Say what you want to update.", {"error": "no_changes"}
        # Through the serializer so the rrule and timezone stay valid and the unique-name race is handled.
        serializer = VisionActionSerializer(
            action,
            data=data,
            partial=True,
            context={"get_team": lambda: self._team, "team_id": self._team.id, "user": self._user},
        )
        if not serializer.is_valid():
            return _first_error(serializer.errors), {"error": "invalid_config"}
        old_enabled, old_name = action.enabled, action.name
        # Atomic with the re-provision, matching `perform_update`: a destination failure has to roll the
        # edit back rather than leave an action whose deliveries describe a state it's no longer in.
        with transaction.atomic():
            updated = serializer.save()
            if updated.enabled != old_enabled or updated.name != old_name:
                provision_delivery(updated, user=self._user, team=self._team)
        state = "It's running on its schedule." if updated.enabled else "It's paused, so it won't run or spend."
        return f"Updated the action. {state}", {"action_id": str(updated.id), "enabled": updated.enabled}


DELETE_ACTION_TOOL_DESCRIPTION = """
Use this tool to delete a recurring Replay Vision summary or alert.

# When to use
- The user explicitly asks to delete or remove a summary or an alert

# What it does
Deletes the action and its run history, including the reports it produced. That history is not
recoverable, and its delivery destinations stop firing. Pausing keeps the history, so offer
update_replay_vision_action with enabled false first unless the user is clear they want it gone.
"""


class DeleteActionArgs(BaseModel):
    action_id: str = Field(description="The summary or alert to delete, along with its run history.")


class DeleteReplayVisionActionTool(ReplayVisionGatesMixin, MaxTool):
    # Spends nothing, but destroys the reports it produced.
    needs_confirmation: ClassVar[bool] = True
    name: str = "delete_replay_vision_action"
    description: str = DELETE_ACTION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = DeleteActionArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("vision_action", "editor")]

    async def format_dangerous_operation_preview(self, action_id: str = "", **kwargs) -> str:
        return (
            f"**Delete** action {action_id} and every report it has produced. That history is gone for "
            "good, and its Slack or webhook deliveries stop. Pausing it instead keeps the reports."
        )

    async def _arun_impl(self, action_id: str) -> tuple[str, dict[str, Any]]:
        return await self._delete(action_id)

    @database_sync_to_async
    def _delete(self, action_id: str) -> tuple[str, dict[str, Any]]:
        action = self._action_for(action_id)
        if action is None:
            return f"Action {action_id} not found.", {"error": "not_found"}
        # Archive destinations before the row goes, matching `perform_destroy`.
        archive_delivery(action, team=self._team)
        action.delete()
        return "Deleted the action and its reports.", {"action_id": action_id}


RUN_ACTION_TOOL_DESCRIPTION = """
Use this tool to run a Replay Vision summary now, without waiting for its schedule.

# When to use
- The user wants the latest summary immediately rather than at the next scheduled time

# Cost
Running it calls the synthesis model once and bills the project's AI credits, so the user is asked to
confirm. The report is not returned immediately: synthesis takes a little while, and
read_replay_vision_actions with the action's id shows it once it lands.
"""


class RunActionArgs(BaseModel):
    action_id: str = Field(description="The summary to run now.")


class RunReplayVisionActionTool(ReplayVisionGatesMixin, MaxTool):
    # One synthesis call, billed to the project's AI credits.
    needs_confirmation: ClassVar[bool] = True
    name: str = "run_replay_vision_action"
    description: str = RUN_ACTION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = RunActionArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("vision_action", "editor"), ("session_recording", "viewer")]

    async def format_dangerous_operation_preview(self, action_id: str = "", **kwargs) -> str:
        return (
            f"**Run** summary {action_id} now. It calls the synthesis model once and bills the project's "
            "AI credits. This is a one-off; its schedule is unchanged."
        )

    async def _arun_impl(self, action_id: str) -> tuple[str, dict[str, Any]]:
        if not await self._consent_given():
            return self._no_ai_consent()
        return await self._run_now(action_id)

    @database_sync_to_async
    def _run_now(self, action_id: str) -> tuple[str, dict[str, Any]]:
        action = self._action_for(action_id)
        if action is None:
            return f"Action {action_id} not found.", {"error": "not_found"}
        if action.mode != ActionMode.GROUP_SUMMARY:
            return "Only scheduled summaries can be run on demand.", {"error": "not_runnable"}
        # scheduled_at=now anchors this run's observation window; the recurring schedule is untouched.
        _, outcome = start_process_vision_action_workflow(action.id, self._team.id, scheduled_at=timezone.now())
        if outcome is WorkflowStartOutcome.ALREADY_RUNNING:
            return (
                "That summary is already running. Its report will appear when it finishes.",
                {"action_id": action_id, "already_running": True},
            )
        if outcome is not WorkflowStartOutcome.STARTED:
            return "Couldn't start that summary. Try again in a moment.", {"error": "start_failed"}
        return (
            "Started the summary. It takes a little while; read it back with read_replay_vision_actions.",
            {"action_id": action_id},
        )


LABEL_OBSERVATION_TOOL_DESCRIPTION = """
Use this tool to record whether a Replay Vision scanner got a recording right.

# When to use
- The user says a particular result was wrong, or was a good catch
- You've shown a user an observation and they've told you whether they agree with it

# What it does
Saves the team's shared verdict on that observation, with optional written context. It's how a scanner's
accuracy gets tracked, and it feeds prompt improvements later. It costs nothing and doesn't rescan.
"""


class LabelObservationArgs(BaseModel):
    observation_id: str = Field(description="The observation the user is judging.")
    is_correct: bool = Field(description="True if the scanner got this recording right, false if it didn't.")
    feedback: str | None = Field(
        max_length=MAX_FEEDBACK_LENGTH,
        default=None,
        description="Optional note on what it got right or wrong, or what it should have concluded.",
    )


class LabelReplayVisionObservationTool(ReplayVisionGatesMixin, MaxTool):
    # A rating; nothing is scanned.
    needs_confirmation: ClassVar[bool] = False
    name: str = "label_replay_vision_observation"
    description: str = LABEL_OBSERVATION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = LabelObservationArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("replay_scanner", "editor"), ("session_recording", "viewer")]

    async def _arun_impl(
        self, observation_id: str, is_correct: bool, feedback: str | None = None
    ) -> tuple[str, dict[str, Any]]:
        return await self._label(observation_id, is_correct, feedback)

    @database_sync_to_async
    def _label(self, observation_id: str, is_correct: bool, feedback: str | None) -> tuple[str, dict[str, Any]]:
        observation = self._observation_for(observation_id)
        if observation is None:
            return f"Observation {observation_id} not found.", {"error": "not_found"}
        # One shared label per observation, like the API: a second rating replaces the first. Atomic
        # because the one-to-one turns two concurrent labels into an IntegrityError rather than a retry.
        with transaction.atomic():
            ReplayObservationLabel.objects.update_or_create(
                observation=observation,
                team_id=observation.team_id,
                defaults={
                    "is_correct": is_correct,
                    "feedback": (feedback or "").strip()[:MAX_FEEDBACK_LENGTH],
                    "created_by": self._user,
                },
            )
        verdict = "correct" if is_correct else "wrong"
        return f"Recorded that the scanner was {verdict} on that recording.", {
            "observation_id": observation_id,
            "is_correct": is_correct,
        }


IMPACT_TOOL_DESCRIPTION = """
Use this tool to find out how many sessions and people a scanner's findings affected, and optionally to
put those people into a cohort.

# When to use
- The user asks how widespread something is: how many users hit the bug the scanner found
- The user wants to act on the affected people, e.g. target them in a survey or exclude them from an
  experiment

# Narrowing
Pass `tag` for a classifier, or `min_score` / `max_score` for a scorer, to count only the observations
that match that outcome. Leave them unset to count everything the scanner flagged.

# The cohort
Set `create_cohort` to true only when the user has asked for one. It writes a static, dated cohort of
the affected people that does not update itself; asking again makes another one. Counting costs nothing
and scans nothing.
"""


class ImpactArgs(BaseModel):
    scanner_id: str = Field(description="The scanner whose findings to measure.")
    window_days: int = Field(default=30, ge=1, le=365, description="How many days back to count over, 1 to 365.")
    tag: str | None = Field(default=None, description="Classifiers only: count just this tag.")
    min_score: float | None = Field(default=None, description="Scorers only: count scores at or above this.")
    max_score: float | None = Field(default=None, description="Scorers only: count scores at or below this.")
    create_cohort: bool = Field(
        default=False,
        description="Also create a static cohort of the affected people. Only when the user asked for one.",
    )


class AnalyzeReplayVisionImpactTool(ReplayVisionGatesMixin, MaxTool):
    # Counts existing observations; scans nothing.
    name: str = "analyze_replay_vision_impact"
    description: str = IMPACT_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ImpactArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("replay_scanner", "viewer"), ("session_recording", "viewer")]

    async def is_dangerous_operation(self, create_cohort: bool = False, **kwargs) -> bool:
        # Counting is free. Writing a cohort is a lasting artifact in the project, so only that branch asks.
        return create_cohort

    async def format_dangerous_operation_preview(self, **kwargs) -> str:
        return "**Create a cohort** of the people this scanner flagged. It's a static, dated snapshot."

    async def _arun_impl(
        self,
        scanner_id: str,
        window_days: int = 30,
        tag: str | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        create_cohort: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        return await self._analyze(scanner_id, window_days, tag, min_score, max_score, create_cohort)

    @database_sync_to_async
    def _analyze(
        self,
        scanner_id: str,
        window_days: int,
        tag: str | None,
        min_score: float | None,
        max_score: float | None,
        create_cohort: bool,
    ) -> tuple[str, dict[str, Any]]:
        # Cohort creation writes, so it needs editor; counting alone needs only viewer.
        scanner = self._scanner_for(scanner_id, "editor" if create_cohort else "viewer")
        if scanner is None:
            return f"Scanner {scanner_id} not found.", {"error": "not_found"}
        # Raises on filter/scanner-type mismatches the description invites Max to try, and the messages
        # are written for a person, so hand them back instead of crashing the turn.
        try:
            impact = compute_scanner_impact(scanner, window_days, tag=tag, min_score=min_score, max_score=max_score)
        except ValueError as exc:
            return str(exc), {"error": "invalid_filters"}
        artifact: dict[str, Any] = {
            "affected_sessions": impact.affected_sessions,
            "affected_users": impact.affected_users,
            "sessions_without_user": impact.sessions_without_user,
            "window_days": window_days,
        }
        content = (
            f"{impact.affected_sessions} session(s) and {impact.affected_users} identified person(s) over the "
            f"last {window_days} days. {impact.sessions_without_user} session(s) had no identified person."
        )
        if not create_cohort:
            return content, artifact
        # The tool's declared access covers reading the scanner, not writing a cohort. The API checks
        # this separately for the same reason: cohort access isn't implied by the scanner's.
        if not self.user_access_control.check_access_level_for_resource("cohort", required_level="editor"):
            return f"{content} Saving them as a cohort needs cohort edit access.", artifact
        try:
            cohort, members = create_affected_cohort(
                scanner, self._user, window_days, tag=tag, min_score=min_score, max_score=max_score
            )
        except ValueError as exc:
            return f"{content} Couldn't build a cohort: {exc}", artifact
        artifact |= {"cohort_id": cohort.id, "cohort_members": members}
        return (
            f"{content} Put {members} of them into a static cohort, which doesn't update itself.",
            artifact,
        )


SUGGEST_TAGS_TOOL_DESCRIPTION = """
Use this tool to propose additional tags for a classifier scanner, grounded in what it has actually seen.

# When to use
- The user says a classifier's tags don't cover what's showing up in their recordings
- The user asks what other categories they should be classifying into

# What it returns
Suggested tags with a reason for each, drawn from the scanner's own observations and the team's other
classifiers. It only suggests; adding one means updating the scanner's tag vocabulary in the UI, since
changing a classifier's vocabulary affects how every future observation is read. Costs no Replay Vision
credits.
"""


class SuggestTagsArgs(BaseModel):
    scanner_id: str = Field(description="The classifier scanner to suggest additional tags for.")


class SuggestReplayVisionTagsTool(ReplayVisionGatesMixin, MaxTool):
    # Suggests only; nothing is scanned and no scanner is changed.
    needs_confirmation: ClassVar[bool] = False
    name: str = "suggest_replay_vision_tags"
    description: str = SUGGEST_TAGS_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = SuggestTagsArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("replay_scanner", "viewer"), ("session_recording", "viewer")]

    async def _arun_impl(self, scanner_id: str) -> tuple[str, dict[str, Any]]:
        scanner = await self._resolve(scanner_id)
        if scanner is None:
            return f"Scanner {scanner_id} not found.", {"error": "not_found"}
        if scanner.scanner_type != ScannerType.CLASSIFIER:
            return "Only classifier scanners have categories.", {"error": "not_a_classifier"}
        # Pooled rather than thread-sensitive: the model call carries a 90s timeout, and the shared
        # executor would queue every other database operation behind it. Still connection-managed,
        # because the suggestion path reads observations and event definitions.
        return await database_sync_to_async_pool(self._suggest)(scanner)

    @database_sync_to_async
    def _resolve(self, scanner_id: str) -> "ReplayScanner | None":
        return self._scanner_for(scanner_id, "viewer")

    def _suggest(self, scanner: ReplayScanner) -> tuple[str, dict[str, Any]]:
        scanner_id = str(scanner.id)
        try:
            config = scanner.scanner_config or {}
            suggestions = suggest_classifier_tags(
                team=self._team,
                user=self._user,
                prompt=config.get("prompt", ""),
                current_tags=config.get("tags") or [],
                multi_label=bool(config.get("multi_label")),
                allow_freeform_tags=bool(config.get("allow_freeform_tags")),
                scanner=scanner,
                user_access_control=self.user_access_control,
            )
        except Exception:
            logger.exception("replay_vision.max_tools.suggest_tags_failed", scanner_id=scanner_id)
            return "Couldn't come up with tag suggestions just now.", {"error": "suggest_failed"}
        if not suggestions:
            return "Nothing worth adding to that scanner's tags right now.", {"suggestions": []}
        # Model-written over recording content, so it stays behind the fence.
        return as_untrusted_data("suggested tags", [f"{s.tag}: {s.rationale}" for s in suggestions]), {
            "suggestions": [{"tag": s.tag, "rationale": s.rationale} for s in suggestions]
        }
