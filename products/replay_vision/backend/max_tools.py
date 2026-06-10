import re
from textwrap import dedent
from typing import Any

from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.feature_flag import is_replay_vision_enabled
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType

from ee.hogai.tool import MaxTool

# Most recent summaries to feed Max — caps the context size for scanners with large histories.
MAX_SUMMARIES = 100

# Inline citation markers the model emits in summary text; stripped before handing to Max as noise.
_EVENT_ID_CITATION_RE = re.compile(r"\(event_id [0-9a-f]{16}\)", re.IGNORECASE)

DRAFT_PROMPT_TOOL_DESCRIPTION = dedent("""
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
    """).strip()


SUMMARIZE_SUMMARIES_TOOL_DESCRIPTION = dedent("""
    Use this tool to reason across the per-session summaries produced by a Replay Vision *summarizer* scanner.

    # When to use
    - The user asks for common themes, patterns, or a digest across a summarizer scanner's sessions
    - The user asks what users are doing, where they struggle, or what stands out across the summarized recordings
    - The user wants a "summary of the summaries"

    # What it returns
    The scanner's most recent per-session summaries. Synthesize them to answer the user's question —
    surface recurring themes, notable outliers, and concrete takeaways rather than restating each summary.
    """).strip()


VALID_SCANNER_TYPES = {t.value for t in ScannerType}


class DraftScannerPromptArgs(BaseModel):
    prompt: str = Field(description="The finished scanner instruction prompt to fill into the configuration form.")
    scanner_type: str | None = Field(
        default=None,
        description="The scanner type the prompt is for (monitor, classifier, scorer, or summarizer). "
        "Only required when not already available from context.",
    )


class DraftReplayVisionScannerPromptTool(MaxTool):
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
            return "Replay Vision is not enabled for this project.", {"error": "not_enabled"}

        cleaned = prompt.strip()
        if not cleaned:
            return "No prompt to apply. Please provide the drafted prompt text.", {"error": "empty_prompt"}

        resolved_type = scanner_type or self.context.get("scanner_type")
        # Artifact is consumed by the frontend callback, which fills the prompt field in the form.
        return "Drafted a scanner prompt and filled it into the configuration form.", {
            "prompt": cleaned,
            "scanner_type": resolved_type if resolved_type in VALID_SCANNER_TYPES else None,
        }

    @database_sync_to_async
    def _is_enabled(self) -> bool:
        return is_replay_vision_enabled(self._user, self._team)


class SummarizeSummariesArgs(BaseModel):
    scanner_id: str | None = Field(
        default=None,
        description="The summarizer scanner to digest. Only required when not already available from context.",
    )


class SummarizeReplayVisionSummariesTool(MaxTool):
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
            # Generic content — Max may relay it to the user, so don't surface the raw exception.
            # Raw detail stays in the artifact (not user-visible) for debugging.
            return "Something went wrong loading the summaries. Please try again.", {
                "error": "fetch_failed",
                "details": str(e),
            }

    @database_sync_to_async
    def _fetch_and_format(self, scanner_id: str) -> tuple[str, dict[str, Any]]:
        # Gate on the product flag, matching the Vision API viewsets — the tool must not return
        # data when Replay Vision is disabled for the org.
        if not is_replay_vision_enabled(self._user, self._team):
            return "Replay Vision is not enabled for this project.", {"error": "not_enabled"}

        scanner = ReplayScanner.objects.filter(team_id=self._team.id, id=scanner_id).first()
        if scanner is None:
            return f"Scanner {scanner_id} not found.", {"error": "not_found"}
        # Summaries inherit the scanner's RBAC — a team member without viewer access to this scanner
        # must not read its recording-derived output. Treat as not-found so we don't leak existence.
        if not self.user_access_control.check_access_level_for_object(scanner, "viewer"):
            return f"Scanner {scanner_id} not found.", {"error": "forbidden"}
        if scanner.scanner_type != ScannerType.SUMMARIZER:
            return (
                f'Scanner "{scanner.name}" is a {scanner.scanner_type} scanner, not a summarizer.',
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
            clean = _EVENT_ID_CITATION_RE.sub("", summary).strip()
            prefix = f"{created_at:%Y-%m-%d}"
            lines.append(f"- ({prefix}) {f'{title}: ' if title else ''}{clean}")

        if not lines:
            return (
                f'Scanner "{scanner.name}" has no completed summaries yet.',
                {"scanner_id": scanner_id, "summary_count": 0},
            )

        header = f'Recent session summaries from the "{scanner.name}" scanner ({len(lines)} of the latest):'
        content = header + "\n\n" + "\n".join(lines)
        return content, {"scanner_id": scanner_id, "summary_count": len(lines)}
