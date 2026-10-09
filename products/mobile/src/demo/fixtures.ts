import type {
    ActivityEvent,
    DecisionQuestion,
    EvidenceBlock,
    InboxItem,
    InboxReason,
    Person,
    ReportView,
    TaskRunView,
    WorkView,
} from '@/model/types'

import { DEMO_AGENT, DEMO_BRIEFINGS, DEMO_DECISION, type DemoBriefing, type DemoKind } from './briefings'

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
        name: 'Tomás Ruiz',
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
        uuid: 'demo-user-alex',
        name: 'Alex Kim',
        email: 'alex@example.com',
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

function agoToDate(briefing: DemoBriefing, anchor: Date): Date {
    const ms = 'hours' in briefing.ago ? briefing.ago.hours * 3_600_000 : briefing.ago.days * 86_400_000
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
            url: `https://example.com/replay/${sessionId}`,
        })
    }
    return blocks
}

function workFor(briefing: DemoBriefing): WorkView {
    switch (briefing.kind) {
        case 'done':
            return { state: 'done', assignee: briefing.owner }
        case 'decision':
            return { state: 'working', assignee: briefing.owner }
        case 'pr_ready':
            return {
                state: 'in_review',
                assignee: briefing.owner,
                pullRequest: {
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
            pendingDecision: DEMO_DECISION_QUESTION,
        }
    }
    if (briefing.kind === 'pr_ready') {
        return {
            taskId: `${briefing.id}-task`,
            runId: `${briefing.id}-run`,
            status: 'completed',
            stage: 'PR #4190 ready',
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

function reportFor(briefing: DemoBriefing, anchor: Date): ReportView {
    const task = taskFor(briefing)
    return {
        id: briefing.id,
        title: briefing.title,
        sourceProduct: briefing.sourceProduct,
        sourceLabel: briefing.sourceLabel,
        accent: briefing.accent,
        headline: { number: briefing.headNum, rest: briefing.headRest },
        lede: briefing.lede,
        evidence: evidenceFor(briefing),
        facts: briefing.facts.map(([key, title, sub, tone]) => ({ key, title, tone, ...(sub ? { sub } : {}) })),
        metric: {
            label: briefing.metric.label,
            range: briefing.metric.range,
            max: 120,
            bars: briefing.metric.bars.map(([value, hot]) => ({ value, hot: hot === 1 })),
        },
        activity: activityFor(briefing, anchor),
        work: workFor(briefing),
        ...(task ? { task } : {}),
        reviewers: [],
        prompt: briefing.prompt ?? briefing.title,
        contextNote: briefing.contextNote,
    }
}

function itemFor(briefing: DemoBriefing, index: number, anchor: Date): InboxItem {
    const hasAgent = briefing.kind === 'decision' || briefing.kind === 'pr_ready'
    const task = taskFor(briefing)
    return {
        id: briefing.id,
        reportId: briefing.id,
        title: briefing.title,
        sourceProduct: briefing.sourceProduct,
        sourceLabel: briefing.sourceLabel,
        accent: briefing.accent,
        updatedAt: agoToDate(briefing, anchor).toISOString(),
        rank: index + 1,
        reason: REASON_BY_KIND[briefing.kind],
        state: briefing.kind === 'done' ? 'done' : 'open',
        needsInput: briefing.kind === 'decision',
        read: false,
        ...(hasAgent ? { agent: { ...DEMO_AGENT } } : {}),
        ...(task?.stage ? { progressLabel: task.stage } : {}),
    }
}

export function buildDemoFixtures(anchor: Date): DemoFixtures {
    const list = DEMO_BRIEFINGS.map((briefing, index) => ({
        briefing,
        item: itemFor(briefing, index, anchor),
        report: reportFor(briefing, anchor),
    }))
    return { anchor, list, byId: Object.fromEntries(list.map((fixture) => [fixture.report.id, fixture])) }
}
