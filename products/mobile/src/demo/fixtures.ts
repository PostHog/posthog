import { dailyBuckets } from '@/lib/dates'
import { sourceInfo } from '@/model/sources'
import type {
    ActivityEvent,
    DecisionQuestion,
    EvidenceBlock,
    InboxItem,
    InboxReason,
    MetricChartKind,
    MetricSeries,
    MetricValueFormat,
    MetricView,
    Person,
    ReportChartView,
    ReportOwner,
    ReportSignalView,
    ReportView,
    TaskRunView,
    WorkView,
} from '@/model/types'

import {
    DEMO_AGENT,
    DEMO_BRIEFINGS,
    DEMO_DECISION,
    type DemoAgo,
    type DemoBriefing,
    type DemoChart,
    type DemoKind,
    type DemoSupportingMetric,
} from './briefings'

export interface DemoFixture {
    item: InboxItem
    report: ReportView
    briefing: DemoBriefing
}

export interface DemoFixtures {
    anchor: Date
    list: DemoFixture[]
    byId: Record<string, DemoFixture>
}

export const DEMO_DECISION_QUESTION: DecisionQuestion = {
    id: DEMO_DECISION.id,
    question: DEMO_DECISION.question,
    options: DEMO_DECISION.options.map((option) => ({ ...option })),
}

export const DEMO_PEOPLE: Person[] = [
    {
        uuid: 'demo-user-sana',
        name: 'Sana Patel',
        email: 'sana@example.com',
        role: 'Frontend · Reports',
        color: '#1D4AFF',
    },
    {
        uuid: 'demo-user-marcus',
        name: 'Marcus Lee',
        email: 'marcus@example.com',
        role: 'Platform · on call',
        color: '#F54E00',
    },
    {
        uuid: 'demo-user-ines',
        name: 'Ines Moreau',
        email: 'ines@example.com',
        role: 'Product · Analytics',
        color: '#2F8F5B',
    },
    {
        uuid: 'demo-user-tomas',
        name: 'Mateo Ruiz',
        email: 'tomas@example.com',
        role: 'Backend · Jobs',
        color: '#7A4DD6',
    },
    {
        uuid: 'demo-user-priya',
        name: 'Priya Nair',
        email: 'priya@example.com',
        role: 'Frontend · Dashboards',
        color: '#C2410C',
    },
    {
        uuid: 'demo-user-jonah',
        name: 'Jonah Weiss',
        email: 'jonah@example.com',
        role: 'Support engineering',
        color: '#0E7490',
    },
    {
        uuid: 'demo-user-robin',
        name: 'Robin Calloway',
        email: 'robin@example.com',
        role: 'Frontend · Reports',
        color: '#1F1F1C',
    },
]

export const DEMO_ME = DEMO_PEOPLE[6] as Person

const WHEN_PATTERN = /^(Today|Sun|Mon|Tue|Wed|Thu|Fri|Sat) (\d{1,2}):(\d{2}) (AM|PM)$/
const WEEKDAY_INDEX: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }

// A weekday means the most recent such day before today, one to seven days back.
export function parseDemoWhen(when: string, anchor: Date): Date {
    const match = WHEN_PATTERN.exec(when)
    if (!match) {
        throw new Error(`Unrecognized demo time "${when}"`)
    }
    const [, day = '', hourText = '', minuteText = '', meridiem = ''] = match
    const hour12 = Number(hourText) % 12
    const hours = meridiem === 'PM' ? hour12 + 12 : hour12
    const date = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate(), hours, Number(minuteText))
    if (day !== 'Today') {
        const target = WEEKDAY_INDEX[day] ?? 0
        const back = (anchor.getDay() - target + 7) % 7 || 7
        date.setDate(date.getDate() - back)
    }
    return date
}

function agoToDate(ago: DemoAgo, anchor: Date): Date {
    const ms = 'hours' in ago ? ago.hours * 3_600_000 : ago.days * 86_400_000
    return new Date(anchor.getTime() - ms)
}

const REASON_BY_KIND: Record<DemoKind, InboxReason> = {
    done: 'claimed_by_you',
    decision: 'waiting_for_you',
    pr_ready: 'your_pull_request',
    open: 'urgent_for_project',
}

function evidenceFor(briefing: DemoBriefing): EvidenceBlock[] {
    const blocks: EvidenceBlock[] = []
    if (briefing.trace) {
        blocks.push({
            kind: 'trace',
            error: briefing.trace.error,
            frames: briefing.trace.frames.map(([fn, loc]) => ({ fn, loc })),
            footer: briefing.trace.footer,
        })
    }
    if (briefing.quotes) {
        blocks.push({ kind: 'quotes', quotes: briefing.quotes.map(([text, who]) => ({ text, who })) })
    }
    if (briefing.replay) {
        const sessionId = `${briefing.id}-session`
        blocks.push({
            kind: 'replay',
            sessionId,
            meta: briefing.replay.meta,
            count: briefing.replay.count,
            url: demoReplayUrl(sessionId),
        })
    }
    return blocks
}

function demoReplayUrl(sessionId: string): string {
    return `https://example.com/replay/${sessionId}`
}

function signalsFor(briefing: DemoBriefing, anchor: Date): ReportSignalView[] {
    return briefing.signals.map((signal, index) => ({
        id: `${briefing.id}-signal-${index}`,
        sourceProduct: signal.source,
        sourceLabel: sourceInfo(signal.source).label,
        content: signal.content,
        at: agoToDate(signal.ago, anchor).toISOString(),
        ...(signal.sessionId ? { sessionId: signal.sessionId, replayUrl: demoReplayUrl(signal.sessionId) } : {}),
        ...(signal.ticket !== undefined ? { ticketNumber: signal.ticket } : {}),
    }))
}

function workFor(briefing: DemoBriefing): WorkView {
    switch (briefing.kind) {
        case 'done':
            return { state: 'done', assignee: briefing.owner }
        case 'decision':
            return {
                state: 'working',
                assignee: { kind: 'task', name: DEMO_AGENT.name },
                pullRequests: [
                    {
                        url: 'https://github.com/example/app/pull/4191',
                        number: 4191,
                        title: 'Guard missing chart labels',
                        state: 'draft',
                    },
                ],
            }
        case 'pr_ready':
            return {
                state: 'in_review',
                assignee: { kind: 'task', name: DEMO_AGENT.name },
                pullRequests: [
                    {
                        url: 'https://github.com/example/app/pull/4190',
                        number: 4190,
                        title: 'Parse typed date ranges before applyFilter',
                        state: 'open',
                        reviewDecision: 'review_required',
                        filesChanged: 2,
                        additions: 18,
                        deletions: 4,
                        checksPassed: true,
                        note: 'Safari 17 verified on staging',
                    },
                    {
                        url: 'https://github.com/example/app/pull/4188',
                        number: 4188,
                        title: 'Add coverage for typed date ranges',
                        state: 'merged',
                    },
                    {
                        url: 'https://github.com/example/app/pull/4189',
                        number: 4189,
                        title: 'Update filter input handling',
                        state: 'closed',
                    },
                    {
                        url: 'https://github.com/example/app/pull/4192',
                        number: 4192,
                        title: 'Verify filter keyboard behavior',
                        state: 'unknown',
                    },
                ],
            }
        case 'open':
            return { state: 'unclaimed' }
    }
}

function taskFor(briefing: DemoBriefing): TaskRunView | undefined {
    if (briefing.kind === 'decision') {
        return {
            taskId: `${briefing.id}-task`,
            runId: `${briefing.id}-run`,
            status: 'in_progress',
            stage: 'Waiting on you',
            phase: 'idle',
            connection: 'connected',
            pendingDecision: DEMO_DECISION_QUESTION,
        }
    }
    if (briefing.kind === 'pr_ready') {
        return {
            taskId: `${briefing.id}-task`,
            runId: `${briefing.id}-run`,
            status: 'in_progress',
            phase: 'working',
            connection: 'connected',
            stage: 'Checking the filter regression tests',
        }
    }
    return undefined
}

function activityFor(briefing: DemoBriefing, anchor: Date): ActivityEvent[] {
    return briefing.activity.map(([text, when, via], index) => ({
        id: `${briefing.id}-activity-${index}`,
        text,
        at: parseDemoWhen(when, anchor).toISOString(),
        ...(via ? { via } : {}),
    }))
}

export const DEMO_WINDOW_LABEL = 'Last 14 days'

function dailySeries(values: readonly number[], anchor: Date): MetricSeries {
    const days = dailyBuckets(anchor, values.length)
    return { interval: 'day', points: values.map((value, index) => ({ at: days[index] ?? '', value })) }
}

// The fixtures have no query, so they follow the live rule for counts and leave currency as a sum.
function demoChartKind(format: MetricValueFormat): MetricChartKind {
    return format === 'count' || format === 'currency' ? 'bar' : 'line'
}

/** A count adds up over the window; a rate, a duration or an average reads as its latest bucket. */
function windowValue(values: readonly number[], format: MetricValueFormat): number {
    const adds = format === 'count' || format === 'currency'
    return adds ? values.reduce((sum, value) => sum + value, 0) : (values[values.length - 1] ?? 0)
}

function observationFor(briefing: DemoBriefing, anchor: Date): MetricView {
    const { title, format, unit, caption, values, filters } = briefing.observation
    const value = Math.round(windowValue(values, format) * 10) / 10
    return {
        metricId: `${briefing.id}-observation`,
        role: 'primary',
        title,
        ...(caption ? { caption } : {}),
        format: { valueFormat: format, unit: unit ?? null },
        chart: demoChartKind(format),
        interval: 'day',
        snapshot: { value, at: anchor.toISOString(), series: [...values] },
        data: { kind: 'static', series: dailySeries(values, anchor), value },
        windowLabel: DEMO_WINDOW_LABEL,
        filterCount: filters,
        openUrl: `https://example.com/insights/${briefing.id}-observation`,
    }
}

function supportingFor(briefing: DemoBriefing, anchor: Date): MetricView[] {
    return (briefing.supporting ?? []).map(([title, value, format, unit]: DemoSupportingMetric, index) => ({
        metricId: `${briefing.id}-supporting-${index}`,
        role: 'supporting',
        title,
        format: { valueFormat: format, unit: unit ?? null },
        chart: demoChartKind(format),
        interval: 'day',
        snapshot: { value, at: anchor.toISOString(), series: [] },
        data: { kind: 'static', series: { interval: 'day', points: [] }, value },
        windowLabel: DEMO_WINDOW_LABEL,
        filterCount: 0,
    }))
}

function chartsFor(briefing: DemoBriefing, anchor: Date): ReportChartView[] {
    return (briefing.charts ?? []).map((chart: DemoChart) => {
        const format = chart.format ?? 'number'
        return {
            chartId: chart.id,
            title: chart.title,
            ...(chart.caption ? { caption: chart.caption } : {}),
            ...(chart.values
                ? {
                      data: {
                          kind: 'static' as const,
                          series: dailySeries(chart.values, anchor),
                          value: windowValue(chart.values, format),
                      },
                  }
                : {}),
            format: { valueFormat: format, unit: chart.unit ?? null },
            chart: 'line',
            interval: 'day',
            openUrl: `https://example.com/insights/${chart.id}`,
        }
    })
}

/** Fact rows the report screen shows in its byline and chips, so they stay out of the facts list. */
const META_FACT_KEYS: ReadonlySet<string> = new Set(['Source', 'Since', 'Owner'])

function factRow(briefing: DemoBriefing, key: string): DemoBriefing['facts'][number] | undefined {
    return briefing.facts.find(([rowKey]) => rowKey === key)
}

// Since rows carry a detail after " · " ("Mon 7:15 AM · peak 310 an hour"); the byline keeps only the moment.
function sinceFor(briefing: DemoBriefing): string | undefined {
    const title = factRow(briefing, 'Since')?.[1]
    return title ? (title.split(' · ')[0] ?? title) : undefined
}

function ownerFor(briefing: DemoBriefing): ReportOwner {
    const row = factRow(briefing, 'Owner')
    if (!row || row[3] === 'alert') {
        return { kind: 'none' }
    }
    return { kind: row[3] === 'agent' ? 'agent' : 'user', name: row[3] === 'agent' ? DEMO_AGENT.name : row[1] }
}

function reportFor(briefing: DemoBriefing, anchor: Date): ReportView {
    const since = sinceFor(briefing)
    const task = taskFor(briefing)
    return {
        id: briefing.id,
        title: briefing.title,
        sourceProduct: briefing.sourceProduct,
        sourceLabel: briefing.sourceLabel,
        accent: briefing.accent,
        headline: { number: briefing.headNum, rest: briefing.headRest },
        lede: briefing.lede,
        summary: briefing.summary.join('\n\n'),
        evidence: evidenceFor(briefing),
        ...(since ? { since } : {}),
        owner: ownerFor(briefing),
        facts: briefing.facts
            .filter(([key]) => !META_FACT_KEYS.has(key))
            .map(([key, title, sub, tone]) => ({ key, title, tone, ...(sub ? { sub } : {}) })),
        observation: observationFor(briefing, anchor),
        supportingMetrics: supportingFor(briefing, anchor),
        charts: chartsFor(briefing, anchor),
        signals: signalsFor(briefing, anchor),
        activity: activityFor(briefing, anchor),
        work: workFor(briefing),
        ...(task ? { task } : {}),
        ...(briefing.priority ? { priority: briefing.priority } : {}),
        reviewers: [],
        prompt: briefing.prompt ?? briefing.title,
        contextNote: briefing.contextNote,
    }
}

function itemFor(briefing: DemoBriefing, anchor: Date): InboxItem {
    const hasAgent = briefing.kind === 'decision' || briefing.kind === 'pr_ready'
    const task = taskFor(briefing)
    const pullRequest = workFor(briefing).pullRequests?.[0]
    const pullRequestUrl = pullRequest?.url
    const pullRequestState = pullRequest?.state
    return {
        id: briefing.id,
        reportId: briefing.id,
        title: briefing.title,
        sourceProduct: briefing.sourceProduct,
        sourceLabel: briefing.sourceLabel,
        sources: [briefing.sourceProduct],
        accent: briefing.accent,
        createdAt: agoToDate(briefing.ago, anchor).toISOString(),
        updatedAt: agoToDate(briefing.ago, anchor).toISOString(),
        modelScore: null,
        reason: REASON_BY_KIND[briefing.kind],
        state: briefing.kind === 'done' ? 'done' : 'open',
        needsInput: briefing.kind === 'decision',
        read: false,
        ...(hasAgent ? { agent: { ...DEMO_AGENT } } : {}),
        ...(task?.stage ? { progressLabel: task.stage } : {}),
        ...(pullRequestUrl ? { pullRequestUrl } : {}),
        ...(pullRequestState ? { pullRequestState } : {}),
    }
}

export function buildDemoFixtures(anchor: Date): DemoFixtures {
    const list = DEMO_BRIEFINGS.map((briefing) => ({
        briefing,
        item: itemFor(briefing, anchor),
        report: reportFor(briefing, anchor),
    }))
    return { anchor, list, byId: Object.fromEntries(list.map((fixture) => [fixture.report.id, fixture])) }
}
