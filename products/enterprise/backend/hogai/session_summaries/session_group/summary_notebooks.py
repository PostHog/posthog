from django.utils import timezone

from structlog import get_logger

from posthog.models.team import Team
from posthog.models.user import User
from posthog.temporal.ai.session_summary.types.group import SessionSummaryStep

from products.enterprise.backend.hogai.session_summaries.session_group.patterns import (
    EnrichedSessionGroupSummaryPattern,
    EnrichedSessionGroupSummaryPatternsList,
    PatternAssignedEventSegmentContext,
    RawSessionGroupSummaryPattern,
)
from products.enterprise.backend.hogai.session_summaries.utils import logging_session_ids
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.util import (
    TipTapContent,
    TipTapNode,
    create_bullet_list,
    create_empty_paragraph,
    create_heading_with_text,
    create_paragraph_with_content,
    create_paragraph_with_text,
    create_task_list,
    create_text_content,
)

logger = get_logger(__name__)


def format_single_sessions_status(sessions_status: dict[str, bool]) -> TipTapNode:
    """Format sessions status dictionary as a TipTap bullet list"""
    items = []
    for session_id, is_completed in sessions_status.items():
        emoji = "✅" if is_completed else "⏳"
        items.append(f"{emoji} {session_id}")

    bullet_list = create_bullet_list(items)
    return {"type": "doc", "content": [bullet_list]}


def format_extracted_patterns_status(patterns: list[RawSessionGroupSummaryPattern]) -> TipTapNode:
    """Format extracted patterns as a TipTap document with details"""
    content = []

    if not patterns:
        # Show a message when no patterns are extracted yet
        content.append(create_paragraph_with_text("No patterns extracted yet..."))
    else:
        # Create a list of patterns with their details
        pattern_items = []
        for pattern in patterns:
            # Create pattern header with name and severity using TipTap bold
            pattern_name = pattern.pattern_name

            # Build pattern content with proper TipTap formatting
            pattern_content = []

            # Add pattern name in bold with severity
            pattern_header_content = [
                create_text_content(pattern_name, is_bold=True),
                create_text_content(f" ({pattern.severity.value.title()})"),
            ]
            pattern_content.append(create_paragraph_with_content(pattern_header_content))

            # Add description
            desc_content = [create_text_content(pattern.pattern_description)]
            pattern_content.append(create_paragraph_with_content(desc_content))

            # Add as a list item with nested content
            pattern_items.append({"type": "listItem", "content": pattern_content})

        # Add the bullet list
        content.append({"type": "bulletList", "content": pattern_items})

    return {"type": "doc", "content": content}


def format_patterns_assignment_progress() -> TipTapNode:
    """Format patterns assignment progress as a TipTap document with details"""
    # TODO: Replace later when we move pattern assignment chunks into separate activities
    content = [create_paragraph_with_text(f"Generating a report from analyzed patterns and sessions...")]
    return {"type": "doc", "content": content}


class SummaryNotebookIntermediateState:
    """Manages the intermediate state of a notebook during session group summarization."""

    def __init__(self, team_name: str, summary_title: str | None):
        """Initialize the intermediate state with a plan."""
        self.team_name = team_name
        self.summary_title = summary_title
        # Using dict to maintain order (Python 3.7+ guarantees order)
        self.plan_items: dict[SessionSummaryStep, tuple[str, bool]] = {
            SessionSummaryStep.WATCHING_SESSIONS: ("Watch sessions", False),
            SessionSummaryStep.FINDING_PATTERNS: ("Find initial patterns", False),
            SessionSummaryStep.GENERATING_REPORT: ("Generate final report", False),
        }
        # Store content for each step - allows late-arriving updates to be handled correctly
        self.steps_content: dict[SessionSummaryStep, TipTapNode] = {}
        self.current_step: SessionSummaryStep | None = SessionSummaryStep.WATCHING_SESSIONS

    @property
    def current_step_content(self) -> TipTapNode | None:
        """Get the content for the current step."""
        if self.current_step:
            return self.steps_content.get(self.current_step)
        return None

    @property
    def completed_steps(self) -> dict[str, TipTapNode]:
        """Get completed steps with their content."""
        completed = {}
        for step, (step_name, is_completed) in self.plan_items.items():
            if is_completed and step in self.steps_content:
                completed[step_name] = self.steps_content[step]
        return completed

    def update_step_progress(self, content: TipTapNode | None, step: SessionSummaryStep) -> None:
        """Update the step's content and handle step transitions if needed."""
        # Update content for the specific step if provided
        if content:
            self.steps_content[step] = content

        # Only transition if moving forward to a new step
        if step != self.current_step and self._is_forward_transition(step):
            self._complete_and_transition(step)

    def _is_forward_transition(self, new_step: SessionSummaryStep) -> bool:
        """Check if transitioning to new_step would be a forward transition."""
        if self.current_step is None:
            return True

        # Get the order of steps
        steps_list = list(self.plan_items.keys())
        try:
            current_index = steps_list.index(self.current_step)
            new_index = steps_list.index(new_step)
            return new_index > current_index
        except ValueError:
            # If step not found in plan, don't transition
            return False

    def _complete_and_transition(self, new_step: SessionSummaryStep) -> None:
        """Complete current step and transition to the new step."""
        # If no current step - set the new step as current
        if self.current_step is None:
            self.current_step = new_step
            return

        # Mark current step as completed if it exists in plan
        if self.current_step in self.plan_items:
            step_name, _ = self.plan_items[self.current_step]
            self.plan_items[self.current_step] = (step_name, True)

        # Update current step
        self.current_step = new_step

    def format_intermediate_state(self) -> TipTapNode:
        """Convert the intermediate state to TipTap format for display."""
        content = []

        # Add main title
        content.append(
            create_heading_with_text(
                _create_notebook_title(team_name=self.team_name, summary_title=self.summary_title), 1
            )
        )
        content.append(create_empty_paragraph())

        # Add plan section
        content.append(create_heading_with_text("Plan", 2))
        # Extract just the name and completion status for the task list
        task_list_items = [(name, completed) for name, completed in self.plan_items.values()]
        content.append(create_task_list(task_list_items))
        content.append(create_empty_paragraph())
        content.append(_create_line_separator())

        # Add current step content if exists
        if self.current_step_content and self.current_step:
            content.append(create_empty_paragraph())
            # Add header for current step (In progress)
            if self.current_step in self.plan_items:
                step_name, _ = self.plan_items[self.current_step]
                content.append(create_heading_with_text(f"Step: {step_name} (In progress)", 2))
            content.extend(self.current_step_content.get("content", []))

        # Add completed steps in reverse order (most recent first)
        for step_name, step_content in reversed(list(self.completed_steps.items())):
            content.append(create_empty_paragraph())
            content.append(create_heading_with_text(f"Step: {step_name} (Completed)", 2))
            content.extend(step_content.get("content", []))

        return {"type": "doc", "content": content}


def _create_notebook_title(team_name: str, summary_title: str | None) -> str:
    title = f"Session summaries report - {team_name}"
    timestamp = timezone.now().strftime("%Y-%m-%d")
    if summary_title:
        title += f" - {summary_title}"
    title += f" ({timestamp})"
    return title


async def create_empty_notebook_for_summary(user: User, team: Team, summary_title: str | None) -> Notebook:
    """Create an empty notebook for a summary."""
    notebook = await Notebook.objects.acreate(
        team=team,
        title=_create_notebook_title(team_name=team.name, summary_title=summary_title),
        content="",
        created_by=user,
        last_modified_by=user,
    )
    return notebook


async def create_notebook_from_summary_content(
    user: User, team: Team, summary_content: TipTapNode, summary_title: str | None
) -> Notebook:
    """Create a notebook with session summary patterns."""
    notebook = await Notebook.objects.acreate(
        team=team,
        title=_create_notebook_title(team_name=team.name, summary_title=summary_title),
        content=summary_content,
        created_by=user,
        last_modified_by=user,
    )
    return notebook


async def update_notebook_from_summary_content(
    notebook: Notebook | None, summary_content: TipTapNode, session_ids: list[str]
) -> None:
    """Update a notebook with session summary patterns."""
    if not notebook:
        logger.exception(
            f"No notebook_id provided, skipping notebook update (session_ids: {logging_session_ids(session_ids)})"
        )
        return None
    notebook.content = summary_content
    await notebook.asave()


def generate_notebook_content_from_summary(
    summary: EnrichedSessionGroupSummaryPatternsList,
    session_ids: list[str],
    project_name: str,
    team_id: int,
    tasks_available: bool = False,
    summary_title: str | None = None,
) -> TipTapNode:
    """Convert summary data to notebook structure."""
    patterns = summary.patterns
    total_sessions = len(session_ids)
    if not patterns:
        return {
            "type": "doc",
            "content": [
                create_heading_with_text(
                    _create_notebook_title(team_name=project_name, summary_title=summary_title), 1
                ),
                create_paragraph_with_text("No patterns found."),
                create_paragraph_with_text(f"Sessions covered: {', '.join(session_ids)}"),
            ],
        }

    # Sort patterns by severity: critical, high, medium, low
    content = []
    # Title
    content.append(
        create_heading_with_text(_create_notebook_title(team_name=project_name, summary_title=summary_title), 1)
    )
    # Issues to review summary
    session_text = "session" if total_sessions == 1 else "sessions"
    content.append(create_heading_with_text(f"Issues to review – based on {total_sessions} {session_text}", 2))
    # Summary table
    table_content = _create_summary_table(patterns, total_sessions)
    content.extend(table_content)
    content.append(_create_line_separator())

    # Pattern details
    for pattern in patterns:
        pattern_content = _create_pattern_section(
            pattern=pattern, total_sessions=total_sessions, team_id=team_id, tasks_available=tasks_available
        )
        content.extend(pattern_content)

    content.append(
        create_paragraph_with_text(f"Sessions covered: {', '.join(session_ids)}"),
    )

    return {
        "type": "doc",
        "content": content,
    }


def _milliseconds_to_timestamp(milliseconds: int) -> str:
    """Convert milliseconds to HH:MM:SS format."""
    seconds = milliseconds // 1000
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours > 0 else f"{minutes:02d}:{seconds:02d}"


def _create_recording_widget_content(name: str, *, session_id: str, timestamp_ms: int) -> TipTapNode:
    """Create a session recording widget for playing the session within notebook."""
    return {
        "type": "ph-recording",
        "attrs": {
            "id": session_id,
            "noInspector": False,
            # Actually start playback from 5 seconds before the interesting timestamp,
            # so that the user sees what happened just before
            "timestampMs": max(timestamp_ms - 5000, 0),
            "title": f"{name} at {_milliseconds_to_timestamp(timestamp_ms)}",
        },
    }


def _create_line_separator() -> TipTapNode:
    """Create a line separator node."""
    return {"type": "horizontalRule"}


def _create_summary_table(patterns: list[EnrichedSessionGroupSummaryPattern], total_sessions: int) -> TipTapContent:
    """Create summary table-like content using text formatting."""
    severity_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}

    content = []

    # Create a table-like structure using bullet points
    table_items = []

    for pattern in patterns:
        stats = pattern.stats
        sessions_affected = stats.sessions_affected
        sessions_percentage = f"{sessions_affected / total_sessions * 100:.0f}%"
        failure_percentage = f"{(1 - stats.segments_success_ratio) * 100:.0f}%"
        severity_icon = severity_icons.get(
            pattern.severity.value if hasattr(pattern.severity, "value") else pattern.severity, ""
        )
        severity_text = pattern.severity.value if hasattr(pattern.severity, "value") else pattern.severity

        # Create a formatted item for each pattern
        pattern_info = [
            create_text_content(f"{pattern.pattern_name} - ", is_bold=True),
            create_text_content(f"{severity_icon} {severity_text} - "),
            create_text_content(f"{sessions_percentage} ({sessions_affected}) sessions - "),
            create_text_content(f"{failure_percentage} failure rate"),
        ]
        table_items.append(pattern_info)

    content.append(create_bullet_list(table_items))

    return content


def _create_pattern_section(
    pattern: EnrichedSessionGroupSummaryPattern, total_sessions: int, team_id: int, tasks_available: bool
) -> TipTapContent:
    """Create detailed pattern section content."""
    content = []

    # Pattern header
    content.append(create_heading_with_text(pattern.pattern_name, 2))
    # Pattern description
    content.append(create_paragraph_with_text(pattern.pattern_description))

    # Pattern stats
    stats = pattern.stats
    sessions_affected = stats.sessions_affected
    sessions_percentage = f"{sessions_affected / total_sessions * 100:.0f}%"
    success_percentage = f"{stats.segments_success_ratio * 100:.0f}%"
    success_count = int(stats.segments_success_ratio * stats.occurences)
    severity_text = pattern.severity.value if hasattr(pattern.severity, "value") else pattern.severity
    content.append(
        create_paragraph_with_content(
            [create_text_content("How severe it is: ", is_bold=True), create_text_content(severity_text.title())]
        )
    )
    content.append(
        create_paragraph_with_content(
            [
                create_text_content("How many sessions affected: ", is_bold=True),
                create_text_content(f"{sessions_percentage} ({sessions_affected} out of {total_sessions})"),
            ]
        )
    )
    content.append(
        create_paragraph_with_content(
            [
                create_text_content("How often users succeed, despite the pattern: ", is_bold=True),
                create_text_content(f"{success_percentage} ({success_count} out of {stats.occurences})"),
            ]
        )
    )

    # Detection indicators
    content.append(
        create_paragraph_with_content(
            [create_text_content("🔍 "), create_text_content("How we detect this:", is_bold=True)]
        )
    )
    # Convert indicators to bullet list
    content.append(create_bullet_list(pattern.indicators))

    if tasks_available:
        try:
            task_block = _create_task_block(pattern)
            if task_block is not None:
                content.append(task_block)
        except Exception:
            logger.exception(f"Failed to create task for pattern {pattern.pattern_name}")
            pass

    # Examples section, collapsed to avoid overwhelming the user
    content.append(create_heading_with_text("Examples", 3, collapsed=True))
    # TODO: Decide if to limit examples (or create some sort of collapsible section in notebooks)
    events_to_show = pattern.events
    for event_data in events_to_show:
        example_content = _create_example_section(event_data=event_data, team_id=team_id)
        content.append(_create_line_separator())
        content.extend(example_content)
    content.append(_create_line_separator())
    return content


def _create_task_block(pattern: EnrichedSessionGroupSummaryPattern) -> TipTapNode | None:
    """Build a TipTap node to create a Task from a pattern.

    Returns a `ph-task-create` node with attrs { title, description, severity } or None if invalid.
    """
    # Defensive checks in case the object isn't fully populated
    pattern_name = getattr(pattern, "pattern_name", None)
    pattern_description = getattr(pattern, "pattern_description", None)
    pattern_severity = getattr(pattern, "severity", None)

    if not pattern_name or not pattern_description or not pattern_severity:
        return None

    severity_value = pattern_severity.value if hasattr(pattern_severity, "value") else pattern_severity

    task_description_lines: list[str] = [
        f"Pattern: {pattern_name}",
        f"Severity: {str(severity_value).title()}",
        f"Description: {pattern_description}",
    ]

    # Add a compact list of indicators for quick context (limit to 5)
    indicators = getattr(pattern, "indicators", None)
    if indicators:
        indicators_text = "; ".join(str(x) for x in indicators[:5])
        task_description_lines.append(f"Indicators: {indicators_text}")

    # Include a succinct developer-oriented example derived from the first event (if present)
    first_event = None
    try:
        first_event = next(iter(getattr(pattern, "events", []) or []))
    except Exception:
        first_event = None

    if first_event is not None:
        target_event = getattr(first_event, "target_event", None)
        example_lines: list[str] = [
            "",
            "Example:",
            f"  Segment: {getattr(first_event, 'segment_name', 'Unknown')}",
            f"  What confirmed: {getattr(target_event, 'description', 'Unknown')}",
            f"  Where: {getattr(target_event, 'current_url', 'Unknown')}",
            f"  When: {getattr(target_event, 'milliseconds_since_start', 'Unknown')}ms into session",
        ]

        prev_list = [
            getattr(ev, "description", str(ev)) for ev in getattr(first_event, "previous_events_in_segment", [])[:3]
        ]
        next_list = [
            getattr(ev, "description", str(ev)) for ev in getattr(first_event, "next_events_in_segment", [])[:3]
        ]

        if prev_list:
            example_lines.append(f"  Previous: {'; '.join(prev_list)}")
        if next_list:
            example_lines.append(f"  Next: {'; '.join(next_list)}")

        task_description_lines.extend(example_lines)

    return {
        "type": "ph-task-create",
        "attrs": {
            "title": pattern_name,
            "description": "\n".join(task_description_lines),
            "severity": str(severity_value).title(),
        },
    }


def _create_example_section(event_data: PatternAssignedEventSegmentContext, team_id: int) -> TipTapContent:
    """Create example section content for an event."""
    content = []
    session_id = event_data.target_event.session_id

    # Embedded session recording widget
    content.append(
        _create_recording_widget_content(
            name=event_data.target_event.description,
            session_id=session_id,
            timestamp_ms=event_data.target_event.milliseconds_since_start,
        )
    )

    # Quick summary
    content.append(create_heading_with_text("Quick summary", 4))
    quick_summary_items = [
        [create_text_content("What user was doing: ", is_bold=True), create_text_content(event_data.segment_name)],
        [
            create_text_content("What confirmed the pattern: ", is_bold=True),
            create_text_content(event_data.target_event.description),
        ],
        [
            create_text_content("Where it happened: ", is_bold=True),
            create_text_content(event_data.target_event.current_url or "Unknown"),
        ],
    ]
    content.append(create_bullet_list(quick_summary_items))
    # Outcome section
    content.append(create_heading_with_text("Outcome", 4))
    outcome_items = []
    # What happened before
    if event_data.previous_events_in_segment:
        # Add nested items for previous events
        prev_events_list = []
        for prev_event in event_data.previous_events_in_segment:
            prev_events_list.append(prev_event.description)

        # Create list item with paragraph and nested bullet list as content
        prev_events_content = [
            create_paragraph_with_content([create_text_content("What happened before:", is_bold=True)]),
            create_bullet_list(prev_events_list),
        ]
        outcome_items.append(prev_events_content)
    else:
        outcome_items.append(
            [
                create_text_content("What happened before: ", is_bold=True),
                create_text_content("Nothing, start of the segment"),
            ]
        )

    # What happened after
    if event_data.next_events_in_segment:
        # Add nested items for next events
        next_events_list = []
        for next_event in event_data.next_events_in_segment:
            next_events_list.append(next_event.description)

        # Create list item with paragraph and nested bullet list as content
        next_events_content = [
            create_paragraph_with_content([create_text_content("What happened after:", is_bold=True)]),
            create_bullet_list(next_events_list),
        ]
        outcome_items.append(next_events_content)
    else:
        outcome_items.append(
            [
                create_text_content("What happened after: ", is_bold=True),
                create_text_content("Nothing, end of the segment"),
            ]
        )

    # Outcome
    outcome_status = "Success" if event_data.segment_success else "Failure"
    outcome_items.append(
        [
            create_text_content("What's the outcome: ", is_bold=True),
            create_text_content(f"{outcome_status}. {event_data.segment_outcome}"),
        ]
    )

    content.append(create_bullet_list(outcome_items))

    return content
