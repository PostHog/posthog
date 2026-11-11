"""Invented insight states for the summary styling eval.

Every name, number, and URL here is made up. The event names follow the Hedgebox demo taxonomy and
every URL uses example.com. `results_summary` comes from the production summarizer, so the model
sees values in the same format a real delivery has.

Each case also carries a canned model reply for stub mode. The structured stub returns every
finding as one text item, which is the failure the eval measures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from products.subscriptions.backend.temporal.results_summarizer import build_results_summary

DAYS = ["2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02", "2026-11-09"]
DAILY = ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09"]


@dataclass(frozen=True)
class SummaryCase:
    name: str
    description: str
    current_states: list[dict[str, Any]]
    previous_states: list[dict[str, Any]] | None
    names: list[str]
    stub_findings: list[str]
    stub_markdown: str
    subscription_title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def results_summaries(self) -> list[str]:
        states = [*(self.previous_states or []), *self.current_states]
        return [state["results_summary"] for state in states]

    @property
    def input_text(self) -> str:
        return "\n".join(self.results_summaries)

    def stub_structured_json(self) -> str:
        return json.dumps({"findings": [{"items": [{"kind": "text", "text": text}]} for text in self.stub_findings]})


def _state(
    insight_id: int,
    name: str,
    query_kind: str,
    results: list[Any],
    *,
    timestamp: str,
    description: str = "",
    columns: list[str] | None = None,
    value_format: dict[str, Any] | None = None,
    last_period_incomplete: bool = False,
    comparison_enabled: bool = False,
) -> dict[str, Any]:
    return {
        "insight_id": insight_id,
        "insight_name": name,
        "insight_description": description,
        "query_kind": query_kind,
        "results_summary": build_results_summary(
            query_kind,
            results,
            columns=columns,
            value_format=value_format,
            last_period_incomplete=last_period_incomplete,
        ),
        "timestamp": timestamp,
        "comparison_enabled": comparison_enabled,
    }


def _series(label: str, data: list[float], days: list[str] = DAYS) -> dict[str, Any]:
    return {"label": label, "data": data, "days": days}


def _funnel_step(name: str, count: int, order: int, conversion_rate: int) -> dict[str, Any]:
    return {"name": name, "custom_name": None, "count": count, "order": order, "conversion_rate": conversion_rate}


PREVIOUS_TS = "2026-11-02T09:00:00Z"
CURRENT_TS = "2026-11-09T09:00:00Z"

CASES: list[SummaryCase] = [
    SummaryCase(
        name="trend_percentage_changes",
        description="Weekly trend with clear percentage moves between deliveries",
        previous_states=[
            _state(
                1,
                "Weekly signups",
                "TrendsQuery",
                [
                    _series("signed_up", [1180, 1210, 1195, 1240], DAYS[:4]),
                    _series("uploaded_file", [4310, 4280, 4405, 4390], DAYS[:4]),
                ],
                timestamp=PREVIOUS_TS,
            )
        ],
        current_states=[
            _state(
                1,
                "Weekly signups",
                "TrendsQuery",
                [
                    _series("signed_up", [1210, 1195, 1240, 1463], DAYS[1:]),
                    _series("uploaded_file", [4280, 4405, 4390, 3512], DAYS[1:]),
                ],
                timestamp=CURRENT_TS,
            )
        ],
        names=["Weekly signups", "signed_up", "uploaded_file"],
        stub_findings=[
            "Weekly signups rose 18% to 1,463 in the week of 2026-11-09, up from 1,240 the week before.",
            "uploaded_file fell 20% to 3,512 over the last 7 days, the lowest point in the window.",
        ],
        stub_markdown=(
            "- **Weekly signups** rose **18%** to **1,463** in the week of _2026-11-09_, up from **1,240**.\n"
            "- **uploaded_file** fell **20%** to **3,512** over _the last 7 days_."
        ),
    ),
    SummaryCase(
        name="funnel_step_dropoffs",
        description="Funnel with a large drop between two steps",
        previous_states=None,
        current_states=[
            _state(
                2,
                "Activation",
                "FunnelsQuery",
                [
                    _funnel_step("signed_up", 2400, 0, 100),
                    _funnel_step("uploaded_file", 1440, 1, 60),
                    _funnel_step("upgraded_plan", 168, 2, 7),
                ],
                timestamp=CURRENT_TS,
                description="Signup to first upload to paid plan, last 30 days",
            )
        ],
        names=["Activation", "signed_up", "uploaded_file", "upgraded_plan"],
        stub_findings=[
            "Activation loses most users between uploaded_file and upgraded_plan, where only 168 of 1,440 continue.",
            "60% of the 2,400 users who signed_up went on to upload a file in the last 30 days.",
        ],
        stub_markdown=(
            "- **Activation** loses most users between **uploaded_file** and **upgraded_plan**: "
            "only **168** of **1,440** continue.\n"
            "- **60%** of the **2,400** users who **signed_up** uploaded a file in _the last 30 days_."
        ),
    ),
    SummaryCase(
        name="durations_and_currency",
        description="Currency and duration axis formats",
        previous_states=[
            _state(
                3,
                "Monthly app revenue",
                "TrendsQuery",
                [_series("paid_bill", [980, 1040, 1100, 1150], DAYS[:4])],
                timestamp=PREVIOUS_TS,
                value_format={"prefix": "$"},
            ),
            _state(
                4,
                "Time to first upload",
                "TrendsQuery",
                [_series("uploaded_file", [302400, 331200, 345600, 360000], DAYS[:4])],
                timestamp=PREVIOUS_TS,
                value_format={"format": "duration"},
            ),
        ],
        current_states=[
            _state(
                3,
                "Monthly app revenue",
                "TrendsQuery",
                [_series("paid_bill", [1040, 1100, 1150, 1200], DAYS[1:])],
                timestamp=CURRENT_TS,
                value_format={"prefix": "$"},
            ),
            _state(
                4,
                "Time to first upload",
                "TrendsQuery",
                [_series("uploaded_file", [331200, 345600, 360000, 432000], DAYS[1:])],
                timestamp=CURRENT_TS,
                value_format={"format": "duration"},
            ),
        ],
        names=["Monthly app revenue", "Time to first upload", "paid_bill", "uploaded_file"],
        stub_findings=[
            "Time to first upload got slower, rising 20% from 4d 4h to 5d on November 9.",
            "Monthly app revenue grew 4.3% to $1,200 for the week of Nov 9, up from $1,150.",
        ],
        stub_markdown=(
            "- **Time to first upload** got slower, rising **20%** from **4d 4h** to **5d** on _November 9_.\n"
            "- **Monthly app revenue** grew **4.3%** to **$1,200** for the week of _Nov 9_."
        ),
    ),
    SummaryCase(
        name="dates_and_rolling_windows",
        description="Daily trend with an in-progress final day and weekday patterns",
        previous_states=None,
        current_states=[
            _state(
                5,
                "Daily unique visitors over time",
                "TrendsQuery",
                [_series("$pageview", [5120, 5340, 5290, 5410, 4980, 2710, 2650], DAILY)],
                timestamp=CURRENT_TS,
                last_period_incomplete=True,
                description="Unique visitors to hedgebox.example.com per day",
            )
        ],
        names=["Daily unique visitors over time", "$pageview"],
        stub_findings=[
            "Daily unique visitors over time peaked at 5,410 on Friday, November 6, then fell to 2,710 on Sunday.",
            "Weekend traffic over the past 7 days ran about half of weekday traffic; 2026-11-09 is still in progress.",
        ],
        stub_markdown=(
            "- **Daily unique visitors over time** peaked at **5,410** on _Friday, November 6_, "
            "then fell to **2,710** on _Sunday_.\n"
            "- Weekend traffic over _the past 7 days_ ran about half of weekday traffic; _2026-11-09_ is in progress."
        ),
    ),
    SummaryCase(
        name="nothing_changed",
        description="Metrics moved less than 5% between deliveries",
        previous_states=[
            _state(
                6,
                "Weekly file volume",
                "TrendsQuery",
                [
                    _series("uploaded_file", [8120, 8090, 8150, 8110], DAYS[:4]),
                    _series("downloaded_file", [12040, 12110, 11980, 12060], DAYS[:4]),
                ],
                timestamp=PREVIOUS_TS,
            )
        ],
        current_states=[
            _state(
                6,
                "Weekly file volume",
                "TrendsQuery",
                [
                    _series("uploaded_file", [8090, 8150, 8110, 8140], DAYS[1:]),
                    _series("downloaded_file", [12110, 11980, 12060, 12020], DAYS[1:]),
                ],
                timestamp=CURRENT_TS,
            )
        ],
        names=["Weekly file volume", "uploaded_file", "downloaded_file"],
        stub_findings=["Weekly file volume held steady, with uploaded_file at 8,140 and downloaded_file at 12,020."],
        stub_markdown="- **Weekly file volume** held steady: **uploaded_file** at **8,140**, **downloaded_file** at **12,020**.",
    ),
    SummaryCase(
        name="event_list_with_links",
        description="Raw event rows with page URLs the summary should link",
        previous_states=None,
        current_states=[
            _state(
                7,
                "Recent shared file links",
                "EventsQuery",
                [
                    ["shared_file_link", "https://hedgebox.example.com/files/a1b2c3/", "2026-11-09T08:41:00Z"],
                    ["shared_file_link", "https://hedgebox.example.com/files/d4e5f6/", "2026-11-09T07:12:00Z"],
                    ["shared_file_link", "https://hedgebox.example.com/files/a1b2c3/", "2026-11-08T22:05:00Z"],
                    ["downloaded_file", "https://hedgebox.example.com/files/a1b2c3/", "2026-11-08T21:47:00Z"],
                ],
                timestamp=CURRENT_TS,
                columns=["event", "properties.$current_url", "timestamp"],
                description="Last 100 sharing events",
            )
        ],
        names=["Recent shared file links", "shared_file_link", "downloaded_file"],
        stub_findings=[
            "The 4 returned events span 2026-11-08 to 2026-11-09, so this covers only the last day of sharing.",
            "shared_file_link fired 3 times, twice for https://hedgebox.example.com/files/a1b2c3/.",
        ],
        stub_markdown=(
            "- The **4** returned events span _2026-11-08_ to _2026-11-09_, covering only the last day.\n"
            "- **shared_file_link** fired **3** times, twice for "
            "[files/a1b2c3](https://hedgebox.example.com/files/a1b2c3/)."
        ),
    ),
    SummaryCase(
        name="initial_summary_multi_insight",
        description="First delivery with no previous state, two insights",
        previous_states=None,
        current_states=[
            _state(
                8,
                "Bills paid",
                "TrendsQuery",
                [_series("paid_bill", [312, 298, 341, 356, 372], DAYS)],
                timestamp=CURRENT_TS,
            ),
            _state(
                9,
                "New user retention",
                "RetentionQuery",
                [
                    {"label": "Week 0", "values": [{"count": 1200}, {"count": 504}, {"count": 396}]},
                    {"label": "Week 1", "values": [{"count": 1150}, {"count": 437}]},
                ],
                timestamp=CURRENT_TS,
            ),
        ],
        names=["Bills paid", "New user retention", "paid_bill"],
        stub_findings=[
            "Bills paid reached 372 in the week of Nov 9, the highest of the last 5 weeks.",
            "New user retention for the Week 0 cohort is 33%, with 396 of 1,200 users still active.",
        ],
        stub_markdown=(
            "- **Bills paid** reached **372** in the week of _Nov 9_, the highest of _the last 5 weeks_.\n"
            "- **New user retention** for the Week 0 cohort is **33%**, with **396** of **1,200** users active."
        ),
    ),
    SummaryCase(
        name="breakdown_with_new_insight",
        description="Breakdown series plus an insight added since the last delivery",
        subscription_title="Hedgebox weekly growth",
        previous_states=[
            _state(
                10,
                "Uploads by plan",
                "TrendsQuery",
                [
                    _series("personal/free", [2210, 2190, 2240, 2260], DAYS[:4]),
                    _series("business/standard", [1530, 1580, 1610, 1640], DAYS[:4]),
                ],
                timestamp=PREVIOUS_TS,
            )
        ],
        current_states=[
            _state(
                10,
                "Uploads by plan",
                "TrendsQuery",
                [
                    _series("personal/free", [2190, 2240, 2260, 1808], DAYS[1:]),
                    _series("business/standard", [1580, 1610, 1640, 2050], DAYS[1:]),
                ],
                timestamp=CURRENT_TS,
            ),
            _state(
                11,
                "Upgrades this week",
                "TrendsQuery",
                [_series("upgraded_plan", [41, 38, 44, 57], DAYS[1:])],
                timestamp=CURRENT_TS,
            ),
        ],
        names=["Uploads by plan", "Upgrades this week", "personal/free", "business/standard", "upgraded_plan"],
        stub_findings=[
            "Uploads by plan shifted toward business/standard, which rose 25% to 2,050 while personal/free fell 20% to 1,808.",
            "Upgrades this week, a new insight, shows upgraded_plan at 57 for the week of 2026-11-09.",
        ],
        stub_markdown=(
            "- **Uploads by plan** shifted toward **business/standard**, up **25%** to **2,050**, "
            "while **personal/free** fell **20%** to **1,808**.\n"
            "- **Upgrades this week** shows **upgraded_plan** at **57** for the week of _2026-11-09_."
        ),
    ),
]

CASES_BY_NAME = {case.name: case for case in CASES}
