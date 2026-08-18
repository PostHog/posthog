"""Case specs for the replay-attribution eval, shared by the prompts, the seeder, and the scorers.

Every string an assertion depends on lives here so the three sides can't drift: the file a case
expects, the on-screen text seeded into the element chain, and the route the events carry. The
expected paths are real files in ``PostHog/hedgebox``, which is the repository every sandboxed
eval case clones.

The anchor is computed once at import, so the recording timestamps written into a case's prompt
and the event timestamps its seeder writes to ClickHouse agree within a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

# One day back keeps the seeded window inside any recency filter the agent reaches for, without
# landing events in the future when a worker clock runs ahead.
ANCHOR = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0)

HEDGEBOX_ORIGIN = "https://hedgebox.net"


@dataclass(frozen=True, kw_only=True)
class SeededEvent:
    """One analytics event the seeder writes around a case's anchor."""

    event: str
    # Seconds from the anchor. Negative lands the event before the finding's instant.
    offset_seconds: int
    pathname: str
    elements_chain: str = ""
    properties: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class AttributionCase:
    """One recording moment, the events behind it, and the file a human would open."""

    name: str
    session_id: str
    # Seconds from the start of the recording, the way a Replay Vision finding reports it.
    start_time: int
    pathname: str
    description: str
    expected_path: str
    # Which anchor the case is meant to exercise, and whether an interaction caused the defect.
    tier: str
    cause: str
    events: tuple[SeededEvent, ...]
    # Set when the case tests the scanner-recorded element rather than a re-derived one.
    element: str | None = None

    @property
    def url(self) -> str:
        return f"{HEDGEBOX_ORIGIN}{self.pathname}"

    @property
    def recording_start_time(self) -> datetime:
        return ANCHOR - timedelta(seconds=self.start_time)


def _chain(tag: str, *, text: str, classes: str = "btn") -> str:
    """An element chain in the shape posthog-js writes: `attr__`-prefixed attributes, ancestors after."""
    return (
        f'{tag}.{classes.replace(" ", ".")}:attr__class="{classes}"attr__type="button"'
        f'nth-child="1"nth-of-type="1"text="{text}";'
        'div.flex.items-center:attr__class="flex items-center"nth-child="1"nth-of-type="1";'
        'body:nth-child="2"nth-of-type="1"'
    )


# Real on-screen strings from the Hedgebox app, greppable verbatim in its source.
UPLOAD_BUTTON_TEXT = "📤 Upload file"
PRICING_HEADING_TEXT = "Choose Your Hedgebox Plan"
SIGNUP_PLAN_TEXT = "Choose your plan"

# Real source files in PostHog/hedgebox.
FILES_PAGE = "src/app/files/page.tsx"
PRICING_PAGE = "src/app/pricing/page.tsx"
SIGNUP_PAGE = "src/app/signup/page.tsx"
DATA_MODULE = "src/lib/data.ts"


EXCEPTION_CASE = AttributionCase(
    name="exception_names_the_file",
    session_id="01960000-0000-7000-8000-00000000e001",
    start_time=139,
    pathname="/files",
    description=(
        "The file list went blank and an error card replaced it right after the page finished "
        "loading. The user sat on the empty screen, reloaded once, and got the same result."
    ),
    expected_path=DATA_MODULE,
    tier="exception",
    cause="render",
    events=(
        SeededEvent(event="$pageview", offset_seconds=-6, pathname="/files"),
        SeededEvent(
            event="$exception",
            offset_seconds=0,
            pathname="/files",
            properties={
                "$exception_types": ["TypeError"],
                "$exception_values": ["Cannot read properties of undefined (reading 'size')"],
                # The first entry is a framework file, so a case that reads index 1 blindly
                # lands on the wrong one. The customer's own file is second.
                "$exception_sources": ["node_modules/next/dist/client/app-index.js", DATA_MODULE],
            },
        ),
    ),
)

ELEMENT_TEXT_CASE = AttributionCase(
    name="element_text_on_files_page",
    session_id="01960000-0000-7000-8000-00000000e002",
    start_time=64,
    pathname="/files",
    description=(
        "The user pressed the upload control and nothing happened on screen. No progress bar, no "
        "new row in the list, no error. They pressed it three more times before giving up."
    ),
    expected_path=FILES_PAGE,
    tier="text",
    cause="interaction",
    events=(
        SeededEvent(event="$pageview", offset_seconds=-11, pathname="/files"),
        SeededEvent(
            event="$autocapture",
            offset_seconds=0,
            pathname="/files",
            elements_chain=_chain("button", text=UPLOAD_BUTTON_TEXT, classes="btn btn-primary"),
            properties={"$event_type": "click"},
        ),
        SeededEvent(
            event="$dead_click",
            offset_seconds=1,
            pathname="/files",
            elements_chain=_chain("button", text=UPLOAD_BUTTON_TEXT, classes="btn btn-primary"),
            properties={"$event_type": "click"},
        ),
    ),
)

ROUTE_ONLY_CASE = AttributionCase(
    name="route_only_render_failure",
    session_id="01960000-0000-7000-8000-00000000e003",
    start_time=22,
    pathname="/pricing",
    description=(
        "The plan cards overlapped the heading and the middle card's price was cut off behind the "
        "card next to it. The user scrolled up and down twice, then left the page."
    ),
    expected_path=PRICING_PAGE,
    tier="route",
    cause="render",
    # Nothing interactive at the moment: a layout break has no click behind it. The only anchor is
    # the route, which is what the fallback path has to use instead of inventing an element.
    events=(SeededEvent(event="$pageview", offset_seconds=-4, pathname="/pricing"),),
)

SCANNER_ELEMENT_CASE = AttributionCase(
    name="scanner_recorded_element_on_signup",
    session_id="01960000-0000-7000-8000-00000000e004",
    start_time=95,
    pathname="/signup",
    description=(
        "The plan step of the signup form showed no selectable plans, just the heading and empty "
        "space below it. The user could not continue and abandoned the form."
    ),
    expected_path=SIGNUP_PAGE,
    tier="text",
    cause="interaction",
    # The scanner read this off the event log at the finding's moment, so research should prefer it
    # over re-deriving one from the window.
    element=SIGNUP_PLAN_TEXT,
    events=(
        SeededEvent(event="$pageview", offset_seconds=-8, pathname="/signup"),
        SeededEvent(
            event="$autocapture",
            offset_seconds=0,
            pathname="/signup",
            elements_chain=_chain("button", text=SIGNUP_PLAN_TEXT, classes="btn btn-outline"),
            properties={"$event_type": "click"},
        ),
    ),
)

ALL_CASES: tuple[AttributionCase, ...] = (
    EXCEPTION_CASE,
    ELEMENT_TEXT_CASE,
    ROUTE_ONLY_CASE,
    SCANNER_ELEMENT_CASE,
)


@dataclass(frozen=True, kw_only=True)
class ScoutAttributionCase:
    """The same recording moment, handed to a scout instead of to report research.

    A scout has no checkout, so it cannot answer with a file. It answers with the anchor — the
    string a reader would grep for — and the tier that anchor rests on, which is what its skill
    now tells it to carry into a report.
    """

    name: str
    moment: AttributionCase
    # Which scout body the case exercises; picks the skill directory and the brief it gets.
    scout: Literal["session_replay", "replay_vision"]
    expected_anchor: str

    @property
    def expected_tier(self) -> str:
        return self.moment.tier

    @property
    def element_expected(self) -> bool:
        """A route-tier moment has no element behind it, so claiming one is an invention."""
        return self.moment.tier != "route"


SCOUT_CLUSTER_ELEMENT_CASE = ScoutAttributionCase(
    name="scout_cluster_element_text",
    moment=ELEMENT_TEXT_CASE,
    scout="session_replay",
    expected_anchor=UPLOAD_BUTTON_TEXT,
)

SCOUT_COHORT_EXCEPTION_CASE = ScoutAttributionCase(
    name="scout_cohort_exception",
    moment=EXCEPTION_CASE,
    scout="session_replay",
    expected_anchor=DATA_MODULE,
)

SCOUT_CLUSTER_NO_ELEMENT_CASE = ScoutAttributionCase(
    name="scout_cluster_without_an_element",
    moment=ROUTE_ONLY_CASE,
    scout="session_replay",
    expected_anchor=ROUTE_ONLY_CASE.pathname,
)

SCOUT_SCANNER_FINDING_CASE = ScoutAttributionCase(
    name="scout_scanner_finding",
    moment=SCANNER_ELEMENT_CASE,
    scout="replay_vision",
    expected_anchor=SIGNUP_PLAN_TEXT,
)

ALL_SCOUT_CASES: tuple[ScoutAttributionCase, ...] = (
    SCOUT_CLUSTER_ELEMENT_CASE,
    SCOUT_COHORT_EXCEPTION_CASE,
    SCOUT_CLUSTER_NO_ELEMENT_CASE,
    SCOUT_SCANNER_FINDING_CASE,
)
