"""Ready-made web analytics questions: the common jobs a web analytics user asks an agent to do.

Each question names the tools that answer it and the shape of the answer, so an agent asked it word for word
can answer it end to end. The eval suite asks every question here and scores the answer against an oracle.
"""

from __future__ import annotations

from collections.abc import Mapping

from posthog.dataclasses import frozen


@frozen
class ReadyPrompt:
    name: str
    tools: tuple[str, ...]
    text: str
    argument_names: tuple[str, ...] = ()


def render_ready_prompt(prompt: ReadyPrompt, arguments: Mapping[str, str] | None = None) -> str:
    lines = [
        f"{name}: {value.strip()}"
        for name in prompt.argument_names
        if (value := (arguments or {}).get(name, "")) and value.strip()
    ]
    return f"{prompt.text}\n\n" + "\n".join(lines) if lines else prompt.text


READY_PROMPTS: tuple[ReadyPrompt, ...] = (
    ReadyPrompt(
        name="web-analytics-weekly-summary",
        tools=("web-analytics-weekly-digest",),
        text=(
            "How did my website do last week?\n"
            "\n"
            "Use `web-analytics-weekly-digest` with the defaults (the last 7 complete days, compared with the 7 days before).\n"
            "Answer with the exact dates covered, then unique visitors, pageviews, sessions, bounce rate and average session duration, each with its change against the previous period.\n"
            "Then list the top pages, the top traffic sources and any goal conversions.\n"
            "Say whether internal and test users were excluded."
        ),
    ),
    ReadyPrompt(
        name="web-analytics-traffic-change",
        tools=("query-web-overview", "query-web-stats"),
        text=(
            "Why did my traffic change this week?\n"
            "\n"
            'First use `query-web-overview` with `compareFilter: { compare: true }` and `dateRange: { date_from: "-7d" }` to measure the change in visitors over the last 7 complete days against the 7 days before.\n'
            "Then use `query-web-stats` with the same comparison, broken down by `InitialChannelType`, then `InitialReferringDomain`, then `InitialPage`, and find the rows whose visitor counts moved the most in absolute terms.\n"
            "Answer with the headline change, then the two or three rows that explain most of it, each with its visitors in both periods.\n"
            "Say which days each period covers, and say so if no single source explains the change."
        ),
    ),
    ReadyPrompt(
        name="web-analytics-compare-periods",
        tools=("query-web-overview",),
        text=(
            "Compare this week with last week.\n"
            "\n"
            'Use `query-web-overview` with `dateRange: { date_from: "-7d" }` and `compareFilter: { compare: true }`.\n'
            "Answer with one line per metric (visitors, pageviews, sessions, bounce rate, average session duration): this period, the previous period and the change in percent.\n"
            "Say which days each period covers. Today's partial day is left out."
        ),
    ),
    ReadyPrompt(
        name="web-analytics-yesterday-vs-last-week",
        tools=("query-web-overview",),
        text=(
            "How did yesterday compare with the same day last week?\n"
            "\n"
            'Use `query-web-overview` with `dateRange: { date_from: "-1dStart", date_to: "-1dEnd" }` and `compareFilter: { compare: true, compare_to: "-7d" }`.\n'
            "Answer with sessions, visitors and average session duration for yesterday and for the same weekday a week earlier, with the change in percent for each."
        ),
    ),
    ReadyPrompt(
        name="web-analytics-top-pages",
        tools=("query-web-stats",),
        text=(
            "What are my top pages?\n"
            "\n"
            'Use `query-web-stats` with `breakdownBy: "Page"`, `includeBounceRate: true`, `doPathCleaning: true` and `limit: 10` over the last 7 days.\n'
            "Answer with the pages ranked by visitors, with visitors, pageviews and bounce rate for each."
        ),
    ),
    ReadyPrompt(
        name="web-analytics-traffic-sources",
        tools=("query-web-stats",),
        text=(
            "Where do my visitors come from?\n"
            "\n"
            'Use `query-web-stats` over the last 7 days twice: once with `breakdownBy: "InitialChannelType"` and once with `breakdownBy: "InitialReferringDomain"`, each with `limit: 10`.\n'
            "Answer with the top channels by visitors and their share of all visitors, then the top five referring domains by visitors.\n"
            "Report `$direct` as direct traffic."
        ),
    ),
    ReadyPrompt(
        name="web-analytics-worst-bounce-landing-pages",
        tools=("query-web-stats",),
        text=(
            "Which landing pages bounce worst?\n"
            "\n"
            'Use `query-web-stats` with `breakdownBy: "InitialPage"`, `includeBounceRate: true`, `doPathCleaning: true` and `limit: 200` over the last 7 days.\n'
            "Leave out landing pages with fewer than 20 visitors, because their bounce rate is noise.\n"
            "Answer with the five remaining pages with the highest bounce rate, worst first, each with its bounce rate and visitors."
        ),
    ),
    ReadyPrompt(
        name="web-analytics-goal-conversion-rate",
        tools=("query-web-overview",),
        text=(
            "What share of my visitors convert to my goal?\n"
            "\n"
            "Use the goal given below. If no goal is given, look up the project's events and actions, pick the likeliest conversion (a sign-up or a purchase) and say which one you picked.\n"
            'Use `query-web-overview` over the last 7 days with `conversionGoal` set to the goal: `{ customEventName: "<event>" }` for an event, `{ actionId: <id> }` for an action.\n'
            "Answer with the conversion rate, the number of visitors who converted and the total number of visitors."
        ),
        argument_names=("goal",),
    ),
    ReadyPrompt(
        name="web-analytics-goal-conversion-by-channel",
        tools=("query-web-stats",),
        text=(
            "Which channels bring the most conversions to my goal?\n"
            "\n"
            "Use the goal given below. If no goal is given, look up the project's events and actions, pick the likeliest conversion (a sign-up or a purchase) and say which one you picked.\n"
            'Use `query-web-stats` with `breakdownBy: "InitialChannelType"` over the last 7 days and `conversionGoal` set to the goal: `{ customEventName: "<event>" }` for an event, `{ actionId: <id> }` for an action.\n'
            "Answer with the channels ranked by total conversions, each with its conversions, visitors and conversion rate."
        ),
        argument_names=("goal",),
    ),
    ReadyPrompt(
        name="web-analytics-worst-web-vitals",
        tools=("query-web-vitals",),
        text=(
            "Which pages have the worst Core Web Vitals?\n"
            "\n"
            'Use `query-web-vitals` with `percentile: "p75"`, `doPathCleaning: true` and `dateRange: { date_from: "-7d" }`, once for each of `LCP`, `INP` and `CLS`.\n'
            "For each metric, answer with the worst pages, worst first, each with its p75 value, its rating (good, needs improvement or poor) and its sample count.\n"
            "Do not report a page with only one or two samples as the worst page. Say if a metric has no data."
        ),
    ),
    ReadyPrompt(
        name="web-analytics-ai-agent-traffic",
        tools=("query-trends",),
        text=(
            "How much of my traffic comes from AI agents and bots?\n"
            "\n"
            "Load the `filtering-bot-traffic` skill if it's available.\n"
            "Use `query-trends` on `$pageview` over the last 7 days, broken down by the event property `$virt_traffic_type`, with `filterTestAccounts: false` so nothing is hidden.\n"
            "Then run `query-trends` again, broken down by `$virt_bot_name`, with a `$virt_traffic_type` exact `AI Agent` event property filter.\n"
            "Answer with the pageviews and share for each traffic type (Regular, AI Agent, Bot, Automation), then the AI agents with the most pageviews."
        ),
    ),
    ReadyPrompt(
        name="web-analytics-audience",
        tools=("query-web-stats",),
        text=(
            "Where are my visitors and what devices do they use?\n"
            "\n"
            'Use `query-web-stats` over the last 7 days twice: once with `breakdownBy: "Country"` and `limit: 10`, once with `breakdownBy: "DeviceType"`.\n'
            "Answer with the top five countries by visitors, then the visitors and share for each device type."
        ),
    ),
    ReadyPrompt(
        name="web-analytics-daily-visitors",
        tools=("query-trends",),
        text=(
            "Show my daily visitors for the last 2 weeks.\n"
            "\n"
            'Use `query-trends` on `$pageview` with the `dau` math, `interval: "day"` and `dateRange: { date_from: "-14d" }`.\n'
            "Answer with the unique visitors for each day. Mark today as a partial day and leave it out of any comparison."
        ),
    ),
)
