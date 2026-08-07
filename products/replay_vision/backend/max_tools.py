import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

import structlog
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field
from rest_framework.exceptions import Throttled

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import async_generate_embedding
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.exceptions import QuotaLimitExceeded
from posthog.models.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.api.scanners import ReplayScannerSerializer
from products.replay_vision.backend.api.vision_actions import VisionActionSerializer
from products.replay_vision.backend.billing import CREDITS_PER_DOLLAR, observation_credits_for_model
from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.embeddings import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_PRODUCT,
    OBSERVATION_EMBEDDING_MODEL,
)
from products.replay_vision.backend.feature_flag import is_replay_vision_actions_enabled, is_replay_vision_enabled
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import ActionMode
from products.replay_vision.backend.observation_formatting import EVENT_ID_CITATION_RE, format_line, read_output
from products.replay_vision.backend.quota import compute_quota_snapshot
from products.replay_vision.backend.scanner_access import (
    is_uuid,
    scanner_for_reading_observations,
    scanners_for_reading_observations,
)
from products.replay_vision.backend.scanner_config import scanner_config_error
from products.replay_vision.backend.scanning import (
    MAX_SESSIONS_PER_SCAN,
    RetryOutcome,
    retry_observation,
    run_inline_scan,
    scan_existing_scanner,
)
from products.replay_vision.backend.tags import clickhouse_slugify_sql, slugify_tag

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

# Default and hard cap on how many observations the search returns to Max's context.
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50
# The cosine-distance scan is exact (brute-force), so cap how many of a team's most-recent embedding rows it
# ranks over. Set well above realistic per-team volume so it only bites a runaway team — keeping latency
# predictable without an HNSW index (which our mandatory tenant/scanner metadata filters wouldn't engage anyway).
_MAX_CANDIDATE_ROWS = 50_000


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

    `spends_credits` defaults to True on purpose. `MaxTool.is_dangerous_operation` defaults to False, so
    a tool that spends the org's credits and forgets to override it charges them with no confirmation,
    and nothing downstream catches that: scanning.py starts the workflow either way. Inverting the
    default here makes the omission cost a needless prompt instead of a needless charge. Read-only tools
    opt out explicitly, with a reason.
    """

    spends_credits: ClassVar[bool] = True

    # Supplied by MaxTool, which every user of this mixin also inherits.
    _user: User
    _team: Team

    async def is_dangerous_operation(self, **kwargs) -> bool:
        return self.spends_credits

    @database_sync_to_async
    def _is_enabled(self) -> bool:
        return is_replay_vision_enabled(self._user, self._team)

    @database_sync_to_async
    def _gates(self) -> tuple[bool, bool]:
        """Both preconditions on one hop. `_is_enabled` can be a network flag evaluation, so running it
        in series ahead of the consent read costs two dispatches for one decision."""
        return is_replay_vision_enabled(self._user, self._team), is_ai_data_processing_approved(self._team.id)

    @staticmethod
    def _not_enabled() -> tuple[str, dict[str, Any]]:
        return "Replay Vision is not enabled for this project.", {"error": "not_enabled"}

    @staticmethod
    def _no_ai_consent() -> tuple[str, dict[str, Any]]:
        return (
            "This organization hasn't enabled AI analysis of recordings, which Replay Vision needs. "
            "An admin can turn it on in organization settings.",
            {"error": "no_ai_consent"},
        )


class DraftReplayVisionScannerPromptTool(ReplayVisionGatesMixin, MaxTool):
    # Reads and form-fills only; nothing here starts a scan.
    spends_credits: ClassVar[bool] = False
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
        if not await self._is_enabled():
            return self._not_enabled()

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
    spends_credits: ClassVar[bool] = False
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
        # Gate on the product flag, matching the Vision API viewsets — the tool must not return
        # data when Replay Vision is disabled for the org.
        if not is_replay_vision_enabled(self._user, self._team):
            return self._not_enabled()

        scanner = scanner_for_reading_observations(self._team.id, scanner_id)
        if scanner is None:
            return f"Scanner {scanner_id} not found.", {"error": "not_found"}
        # Summaries inherit the scanner's RBAC — a team member without viewer access to this scanner
        # must not read its recording-derived output. Treat as not-found so we don't leak existence.
        if not self.user_access_control.check_access_level_for_object(scanner, "viewer"):
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


# Slugify each stored metadata tag before `hasAny`, so the case/format-insensitive match works against rows
# whose fixed-vocab tags were stamped verbatim — no backfill. The caller passes already-slugified values in
# `{tags}`. Built from hardcoded literals only (no user/LLM input), preserving the `_append_filter` invariant.
_TAGS_FILTER_CLAUSE = (
    f"hasAny(arrayMap(t -> {clickhouse_slugify_sql('t')}, JSONExtract(metadata, 'tags', 'Array(String)')), {{tags}})"
)


@dataclass(frozen=True)
class _ObservationFilters:
    """Exact-outcome filters, applied inside the ClickHouse ranking query against the embedding metadata
    (monitor `verdict`, scorer `score`, classifier `tags` are stamped onto each embedding row at write time)."""

    verdict: list[str] | None = None
    tags: list[str] | None = None
    min_score: float | None = None
    max_score: float | None = None

    def where_clauses(self, placeholders: dict[str, "ast.Expr"]) -> list[str]:
        """HogQL predicates over `metadata`, registering their values into `placeholders`. The metadata key is
        absent for scanner types that don't carry it, so each predicate naturally matches only the right type.

        Every clause MUST be added via `_append_filter` — that helper is the only path that pairs a
        hardcoded-literal clause string with a parameterized placeholder. Never append a clause built from
        anything other than a static string literal; user/LLM-controlled input belongs in `value`, not in
        `clause`."""
        clauses: list[str] = []
        if self.verdict:
            self._append_filter(
                clauses, placeholders, "verdict", self.verdict, "JSONExtractString(metadata, 'verdict') IN {verdict}"
            )
        if self.tags:
            self._append_filter(clauses, placeholders, "tags", self.tags, _TAGS_FILTER_CLAUSE)
        if self.min_score is not None:
            self._append_filter(
                clauses,
                placeholders,
                "min_score",
                self.min_score,
                "JSONHas(metadata, 'score') AND JSONExtractFloat(metadata, 'score') >= {min_score}",
            )
        if self.max_score is not None:
            self._append_filter(
                clauses,
                placeholders,
                "max_score",
                self.max_score,
                "JSONHas(metadata, 'score') AND JSONExtractFloat(metadata, 'score') <= {max_score}",
            )
        return clauses

    @staticmethod
    def _append_filter(
        clauses: list[str],
        placeholders: dict[str, "ast.Expr"],
        key: str,
        value: Any,
        clause: str,
    ) -> None:
        """Register one filter atomically: the value goes into `placeholders` (parameterized), the clause is
        the hardcoded literal that references it. The structure/value split lives in one place so callers
        can't half-do it — any future filter must come through here, which makes the "clause is a static
        literal" invariant impossible to break by accident."""
        placeholders[key] = ast.Constant(value=value)
        clauses.append(clause)


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
    spends_credits: ClassVar[bool] = False
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

        # Slugify Max's tag guess ("Frustrated Or Confused" -> "frustrated_or_confused") so it matches the
        # normalized stored side; order-preserving dedup, dropping anything that slugs to empty.
        normalized_tags = list(dict.fromkeys(s for t in (tags or []) if (s := slugify_tag(t)))) or None
        # Verdicts are a closed lowercase enum (yes/no/inconclusive) stored verbatim, so lowercase Max's input
        # to absorb a casing slip ("Yes") that would otherwise silently match nothing.
        normalized_verdict = list(dict.fromkeys(v.strip().lower() for v in (verdict or []) if v.strip())) or None
        filters = _ObservationFilters(
            verdict=normalized_verdict, tags=normalized_tags, min_score=min_score, max_score=max_score
        )
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
        self, scanner_id: str | None, query: str, filters: "_ObservationFilters", limit: int | None
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
        # Gate on the product flag, matching the Vision API viewsets — the tool must not return
        # data when Replay Vision is disabled for the org.
        if not is_replay_vision_enabled(self._user, self._team):
            return None, ("Replay Vision is not enabled for this project.", {"error": "not_enabled"})

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
        filters: "_ObservationFilters",
    ) -> tuple[str, dict[str, Any]]:
        """Sync ClickHouse rank + ORM fetch + format — runs after the embedding HTTP call has resolved."""
        empty = (f"No recordings from {scope_label} matched that search yet.", {"result_count": 0})

        # Filter + rank in one ClickHouse query: the structured outcome filters run against the embedding
        # metadata, so the semantic ranking only ever sees recordings that already match the exact outcome.
        ordered_ids = self._rank_observation_ids(scanner_ids, query_vector, capped_limit, filters)
        if not ordered_ids:
            return empty

        observations = {
            str(obs.id): obs
            for obs in ReplayObservation.objects.filter(
                team_id=self._team.id,
                scanner_id__in=scanner_ids,
                status=ObservationStatus.SUCCEEDED,
                id__in=ordered_ids,
            )
            .select_related("scanner")
            .only("id", "session_id", "scanner_result", "created_at", "scanner__name")
        }

        lines: list[str] = []
        matched_ids: list[str] = []
        for observation_id in ordered_ids:
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
            # Observations inherit the scanner's RBAC — treat missing access as not-found.
            if scanner is None or not self.user_access_control.check_access_level_for_object(scanner, "viewer"):
                return None
            # The scanner name is user-editable and the header sits outside the data fence, so keep it out of
            # tool output entirely (stored-injection guard); the searcher already knows which scanner they're on.
            return [str(scanner.id)], "the selected Replay Vision scanner", False
        readable = self.user_access_control.filter_queryset_by_access_level(
            scanners_for_reading_observations(self._team.id)
        ).values_list("id", flat=True)
        return [str(sid) for sid in readable], "your Replay Vision scanners", True

    def _rank_observation_ids(
        self, scanner_ids: list[str], query_vector: list[float], limit: int, filters: "_ObservationFilters"
    ) -> list[str]:
        """Closest observation ids by cosine distance, restricted to the given scanners — and to the structured
        outcome filters — via the embedding metadata, so filter and rank happen in a single query.

        `min(...)` collapses an observation's multiple renderings (the summarizer's per-facet rows) to its
        single best-matching distance, so each observation appears once.

        The distance scan is exact (brute-force), so we bound it: the inner query takes the most recent
        `_MAX_CANDIDATE_ROWS` matching embedding rows before ranking. Below that volume (all teams at launch
        scale) it's a no-op; a high-volume team is capped to its most recent embeddings, keeping latency
        predictable at the cost of not ranking its oldest observations.
        """
        placeholders: dict[str, ast.Expr] = {
            "embedding": ast.Constant(value=query_vector),
            "model_name": ast.Constant(value=OBSERVATION_EMBEDDING_MODEL.value),
            "product": ast.Constant(value=EMBEDDING_PRODUCT),
            "document_type": ast.Constant(value=EMBEDDING_DOCUMENT_TYPE),
            "team_id": ast.Constant(value=self._team.id),
            "scanner_ids": ast.Constant(value=scanner_ids),
            "candidate_cap": ast.Constant(value=_MAX_CANDIDATE_ROWS),
            "limit": ast.Constant(value=limit),
        }
        filter_clause = "".join(f"\n                  AND {clause}" for clause in filters.where_clauses(placeholders))
        hogql_query = f"""
            SELECT
                document_id,
                min(cosineDistance(embedding, {{embedding}})) AS distance
            FROM (
                SELECT document_id, embedding
                FROM document_embeddings
                WHERE model_name = {{model_name}}
                  AND product = {{product}}
                  AND document_type = {{document_type}}
                  AND team_id = {{team_id}}
                  AND JSONExtractString(metadata, 'scanner_id') IN {{scanner_ids}}{filter_clause}
                ORDER BY timestamp DESC
                LIMIT {{candidate_cap}}
            )
            GROUP BY document_id
            ORDER BY distance ASC
            LIMIT {{limit}}
        """
        tag_queries(product=Product.REPLAY_VISION, feature=Feature.SEMANTIC_SEARCH)
        result = execute_hogql_query(
            query=hogql_query,
            team=self._team,
            user=self._user,
            placeholders=placeholders,
            ch_user=ClickHouseUser.REPLAY_VISION,
        )
        return [row[0] for row in (result.results or [])]


# Everything a scan costs is priced per observation from this model unless a saved scanner names another.
DEFAULT_SCAN_MODEL = ScannerModel.GEMINI_3_FLASH_PREVIEW

# Pinned to the hour the built-in digest uses, so a summary Max sets up fires at the same time as
# every UI-created one rather than at whatever `starts_at` happened to be.
_SUMMARY_HOUR = 8
# The two cadences worth offering in a chat; anything finer belongs in the UI's rrule editor.
# The scan tool takes no tags or scale, so it offers only the types a prompt alone configures.
_INLINE_SCAN_TYPES = {ScannerType.MONITOR, ScannerType.SUMMARIZER}

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


def _spend_sentence(team: Team, model: str, count: int) -> str:
    """The credit sentence every confirmation prompt ends with.

    Spelled out in credits and dollars against what's left, because the whole point of the confirmation
    is that the user can see what the action costs before it happens.
    """
    cost = observation_credits_for_model(model) * count
    remaining = compute_quota_snapshot(team.organization_id).remaining
    if remaining is None:
        return (
            f"about {cost} credits (${cost / CREDITS_PER_DOLLAR:,.2f}). This project has no monthly credit limit set."
        )
    return f"about {cost} credits (${cost / CREDITS_PER_DOLLAR:,.2f}) of the {remaining} left this month."


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
            scanner = self._editable_scanner(scanner_id)
            model = scanner.model if scanner else DEFAULT_SCAN_MODEL
            # The scanner name is user-editable, so it stays out of model-visible tool output; this
            # preview is rendered to the user who owns it, not fed back to the model.
            what = f"the saved scanner '{scanner.name}'" if scanner else f"the saved scanner (id {scanner_id})"
        return f"**Scan {len(sessions)} session(s)** with {what}. This spends {_spend_sentence(self._team, model, len(sessions))}"

    def _editable_scanner(self, scanner_id: str) -> ReplayScanner | None:
        """A saved scanner this user may run.

        Configured only: an inline scan's scanner is a throwaway the reaper may collect, so re-targeting
        one would point a scan at a row that can vanish underneath it.
        """
        if not is_uuid(scanner_id):
            return None
        scanner = ReplayScanner.objects.filter(team_id=self._team.id, id=scanner_id).first()
        if scanner is None or not self.user_access_control.check_access_level_for_object(scanner, "editor"):
            return None
        return scanner

    async def _arun_impl(
        self,
        session_ids: list[str],
        prompt: str | None = None,
        scanner_id: str | None = None,
        scanner_type: str = "monitor",
    ) -> tuple[str, dict[str, Any]]:
        enabled, consent = await self._gates()
        if not enabled:
            return self._not_enabled()
        sessions = _dedup(session_ids)
        if not sessions:
            return "No session ids to scan.", {"error": "no_sessions"}
        if len(sessions) > MAX_SESSIONS_PER_SCAN:
            return (
                f"That's {len(sessions)} recordings; {MAX_SESSIONS_PER_SCAN} is the most one scan can take. "
                "Narrow the selection and try again.",
                {"error": "too_many_sessions"},
            )
        if not consent:
            return self._no_ai_consent()
        return await self._start_scan(sessions, prompt, scanner_id, scanner_type)

    @database_sync_to_async
    def _start_scan(
        self, sessions: list[str], prompt: str | None, scanner_id: str | None, scanner_type: str
    ) -> tuple[str, dict[str, Any]]:
        if scanner_id:
            scanner = self._editable_scanner(scanner_id)
            if scanner is None:
                return f"Scanner {scanner_id} not found.", {"error": "not_found"}
            started, results = scan_existing_scanner(scanner=scanner, session_ids=sessions, user=self._user)
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
    spends_credits: ClassVar[bool] = False
    name: str = "get_replay_vision_quota"
    description: str = QUOTA_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ReplayVisionQuotaArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("replay_scanner", "viewer")]

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        if not await self._is_enabled():
            return self._not_enabled()
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
        observation = self._editable_observation(observation_id)
        if observation is None:
            return f"Retry observation {observation_id}"
        spend = _spend_sentence(self._team, observation.scanner.model, 1)
        return f"**Scan recording {observation.session_id} again**, replacing the failed result. This spends {spend}"

    def _editable_observation(self, observation_id: str) -> ReplayObservation | None:
        """An observation this user may retry. Observations inherit their scanner's RBAC, and both the
        preview and the execution path need the same answer."""
        if not is_uuid(observation_id):
            return None
        observation = (
            ReplayObservation.objects.filter(team_id=self._team.id, id=observation_id).select_related("scanner").first()
        )
        if observation is None or not self.user_access_control.check_access_level_for_object(
            observation.scanner, "editor"
        ):
            return None
        return observation

    async def _arun_impl(self, observation_id: str) -> tuple[str, dict[str, Any]]:
        enabled, consent = await self._gates()
        if not enabled:
            return self._not_enabled()
        if not consent:
            return self._no_ai_consent()
        return await self._retry(observation_id)

    @database_sync_to_async
    def _retry(self, observation_id: str) -> tuple[str, dict[str, Any]]:
        observation = self._editable_observation(observation_id)
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
        # Argument-dependent, so the mixin's `spends_credits` doesn't decide it: a disabled scanner has
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
        is_on, consent = await self._gates()
        if not is_on:
            return self._not_enabled()
        # Not gated on `enabled`: the serializer refuses to create either kind without consent, so
        # checking only for enabled ones turned the disabled path into an unhandled exception.
        if not consent:
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
        # daily digest, and the lifecycle event. A scanner Max makes should be the same object the UI makes.
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
    spends_credits: ClassVar[bool] = True
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
        # Actions sit behind their own flag, and the API 404s without it. Checking only the product flag
        # would let Max create a scheduled job on a project that can't see or manage it.
        if not await self._actions_enabled():
            return "Replay Vision actions are not enabled for this project.", {"error": "not_enabled"}
        return await self._create(scanner_id, name, cadence, focus)

    @database_sync_to_async
    def _actions_enabled(self) -> bool:
        return is_replay_vision_enabled(self._user, self._team) and is_replay_vision_actions_enabled(
            self._user, self._team
        )

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
