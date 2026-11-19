// PROTOTYPE (throwaway, branch prototype/messaging-overview-calendar, PostHog/michaelr-context#420).
// Every name, address and number below is invented for the prototype. Nothing comes from production.
import { dayjs } from 'lib/dayjs'

export type EntryKind = 'broadcast' | 'workflow' | 'transactional'
export type EntryState = 'draft' | 'scheduled' | 'sending' | 'sent' | 'failed' | 'paused'
export type Channel = 'email' | 'sms' | 'push'

export interface EntryResults {
    sent: number
    delivered: number
    opened: number
    clicked: number
    bounced: number
    unsubscribed: number
}

/** One message going out at one time: a broadcast, or one run of a scheduled workflow. */
export interface CalendarEntry {
    id: string
    kind: EntryKind
    name: string
    state: EntryState
    at: dayjs.Dayjs
    channel: Channel
    audience: string
    people: number
    createdBy: string
    /** Set for a run of a repeating workflow. */
    repeatId?: string
    results?: EntryResults
    error?: string
}

export interface RepeatingWorkflow {
    id: string
    name: string
    rule: string
    channel: Channel
    audience: string
    peoplePerRun: number
    /** Days on which it runs, from today: returns true for a day that has a run. */
    runsOn: (day: dayjs.Dayjs) => boolean
    hour: number
}

/** Messages that no schedule plans: transactional emails and event-triggered workflows, counted per day. */
export interface DayVolume {
    day: string
    transactional: number
    triggered: number
    failed: number
    byTemplate: { name: string; count: number }[]
}

export const TODAY = dayjs().startOf('day')
export const TIMEZONE_LABEL = 'UTC'

// A small deterministic generator, so the same day always shows the same number.
function noise(seed: number): number {
    const x = Math.sin(seed * 9301 + 49297) * 233280
    return x - Math.floor(x)
}

function day(offset: number, hour = 9, minute = 0): dayjs.Dayjs {
    return TODAY.add(offset, 'day').hour(hour).minute(minute)
}

function results(sent: number, open = 0.42, click = 0.06): EntryResults {
    const delivered = Math.round(sent * 0.982)
    return {
        sent,
        delivered,
        opened: Math.round(delivered * open),
        clicked: Math.round(delivered * click),
        bounced: sent - delivered,
        unsubscribed: Math.round(sent * 0.002),
    }
}

export const REPEATING: RepeatingWorkflow[] = [
    {
        id: 'r-digest',
        name: 'Weekly digest',
        rule: 'Every Monday at 8:00',
        channel: 'email',
        audience: 'Active users',
        peoplePerRun: 4210,
        runsOn: (d) => d.day() === 1,
        hour: 8,
    },
    {
        id: 'r-trial',
        name: 'Trial ending reminder',
        rule: 'Every day at 10:00',
        channel: 'email',
        audience: 'Trials ending in 3 days',
        peoplePerRun: 140,
        runsOn: () => true,
        hour: 10,
    },
    {
        id: 'r-sms',
        name: 'Appointment reminder',
        rule: 'Every weekday at 7:30',
        channel: 'sms',
        audience: 'Bookings for tomorrow',
        peoplePerRun: 85,
        runsOn: (d) => d.day() >= 1 && d.day() <= 5,
        hour: 7,
    },
    {
        id: 'r-usage',
        name: 'Monthly usage report',
        rule: 'On the 1st of every month at 7:00',
        channel: 'email',
        audience: 'Account owners',
        peoplePerRun: 1830,
        runsOn: (d) => d.date() === 1,
        hour: 7,
    },
]

const ONE_OFF: CalendarEntry[] = [
    {
        id: 'b-oct-update',
        kind: 'broadcast',
        name: 'October product update',
        state: 'sent',
        at: day(-18, 15),
        channel: 'email',
        audience: 'Newsletter subscribers',
        people: 12480,
        createdBy: 'Robin Example',
        results: results(12480, 0.47, 0.08),
    },
    {
        id: 'b-webinar',
        kind: 'broadcast',
        name: 'Webinar invite: funnels in practice',
        state: 'sent',
        at: day(-9, 16),
        channel: 'email',
        audience: 'Product managers',
        people: 3210,
        createdBy: 'Sam Example',
        results: results(3210, 0.38, 0.11),
    },
    {
        id: 'w-beta',
        kind: 'workflow',
        name: 'Beta invite, wave 2',
        state: 'sent',
        at: day(-4, 11),
        channel: 'email',
        audience: 'Beta waitlist',
        people: 960,
        createdBy: 'Robin Example',
        results: results(960, 0.61, 0.24),
    },
    {
        id: 'b-survey',
        kind: 'broadcast',
        name: 'Pricing page survey',
        state: 'failed',
        at: day(-1, 14),
        channel: 'email',
        audience: 'Visited pricing in 30 days',
        people: 5000,
        createdBy: 'Sam Example',
        results: results(1204, 0.29, 0.05),
        error: 'Stopped after 1,204 of 5,000 messages. The sending domain mail.example.com failed its DKIM check.',
    },
    {
        id: 'p-release',
        kind: 'broadcast',
        name: 'Mobile app release note',
        state: 'sent',
        at: day(-2, 18),
        channel: 'push',
        audience: 'Mobile app users',
        people: 7400,
        createdBy: 'Alex Example',
        results: results(7400, 0.12, 0.04),
    },
    {
        id: 'b-bf',
        kind: 'broadcast',
        name: 'Black Friday early access',
        state: 'scheduled',
        at: day(2, 9),
        channel: 'email',
        audience: 'Paying customers',
        people: 18900,
        createdBy: 'Robin Example',
    },
    {
        id: 'b-bf-sms',
        kind: 'broadcast',
        name: 'Black Friday SMS',
        state: 'scheduled',
        at: day(2, 12),
        channel: 'sms',
        audience: 'SMS opt-ins',
        people: 2100,
        createdBy: 'Robin Example',
    },
    {
        id: 'w-dormant',
        kind: 'workflow',
        name: 'Re-engage dormant trials',
        state: 'scheduled',
        at: day(5, 10),
        channel: 'email',
        audience: 'Trials with no login in 14 days',
        people: 1320,
        createdBy: 'Alex Example',
    },
    {
        id: 'b-holiday',
        kind: 'broadcast',
        name: 'Holiday support hours',
        state: 'scheduled',
        at: day(12, 9),
        channel: 'email',
        audience: 'All customers',
        people: 24100,
        createdBy: 'Sam Example',
    },
    {
        id: 'b-feature',
        kind: 'broadcast',
        name: 'Feature launch: shared dashboards',
        state: 'scheduled',
        at: day(9, 16),
        channel: 'email',
        audience: 'Newsletter subscribers',
        people: 12900,
        createdBy: 'Alex Example',
    },
    {
        id: 'b-year',
        kind: 'broadcast',
        name: 'Year in review',
        state: 'scheduled',
        at: day(27, 15),
        channel: 'email',
        audience: 'Newsletter subscribers',
        people: 13100,
        createdBy: 'Robin Example',
    },
    {
        id: 'b-paused',
        kind: 'broadcast',
        name: 'Partner program invite',
        state: 'paused',
        at: day(6, 13),
        channel: 'email',
        audience: 'Agencies',
        people: 640,
        createdBy: 'Sam Example',
    },
]

export const DRAFTS: { id: string; name: string; kind: EntryKind; edited: string; by: string }[] = [
    { id: 'd-dec', name: 'December product update', kind: 'broadcast', edited: '2 days ago', by: 'Robin Example' },
    { id: 'd-sms', name: 'Winback SMS', kind: 'broadcast', edited: '5 days ago', by: 'Alex Example' },
    { id: 'd-onb', name: 'Onboarding for teams', kind: 'workflow', edited: 'yesterday', by: 'Sam Example' },
]

/** Every entry from `start` to `end`, with each run of a repeating workflow as its own entry. */
export function entriesBetween(start: dayjs.Dayjs, end: dayjs.Dayjs): CalendarEntry[] {
    const entries = ONE_OFF.filter((entry) => !entry.at.isBefore(start) && entry.at.isBefore(end))
    for (let d = start.startOf('day'); d.isBefore(end); d = d.add(1, 'day')) {
        for (const repeat of REPEATING) {
            if (!repeat.runsOn(d)) {
                continue
            }
            const at = d.hour(repeat.hour).minute(repeat.id === 'r-sms' ? 30 : 0)
            const past = at.isBefore(dayjs())
            const offset = d.diff(TODAY, 'day')
            const people = Math.round(repeat.peoplePerRun * (0.85 + noise(offset + repeat.hour) * 0.3))
            entries.push({
                id: `${repeat.id}-${d.format('YYYY-MM-DD')}`,
                kind: 'workflow',
                name: repeat.name,
                state: past ? 'sent' : 'scheduled',
                at,
                channel: repeat.channel,
                audience: repeat.audience,
                people,
                createdBy: 'Alex Example',
                repeatId: repeat.id,
                results: past ? results(people, 0.35 + noise(offset) * 0.2, 0.05) : undefined,
            })
        }
    }
    return entries.sort((a, b) => a.at.valueOf() - b.at.valueOf())
}

export function volumeFor(d: dayjs.Dayjs): DayVolume | null {
    if (d.isAfter(TODAY, 'day')) {
        return null
    }
    const offset = d.diff(TODAY, 'day')
    const weekend = d.day() === 0 || d.day() === 6
    const scale = (weekend ? 0.55 : 1) * (d.isSame(TODAY, 'day') ? 0.45 : 1)
    const templates = [
        { name: 'Password reset', count: Math.round((420 + noise(offset) * 160) * scale) },
        { name: 'Receipt', count: Math.round((380 + noise(offset + 1) * 120) * scale) },
        { name: 'Magic link', count: Math.round((260 + noise(offset + 2) * 90) * scale) },
        { name: 'Team invite', count: Math.round((40 + noise(offset + 3) * 30) * scale) },
    ]
    return {
        day: d.format('YYYY-MM-DD'),
        transactional: templates.reduce((sum, t) => sum + t.count, 0),
        triggered: Math.round((310 + noise(offset + 4) * 140) * scale),
        failed: offset === -1 ? 38 : Math.round(noise(offset + 5) * 4),
        byTemplate: templates,
    }
}

export const KIND_LABEL: Record<EntryKind, string> = {
    broadcast: 'Broadcast',
    workflow: 'Workflow',
    transactional: 'Transactional',
}

export const STATE_LABEL: Record<EntryState, string> = {
    draft: 'Draft',
    scheduled: 'Scheduled',
    sending: 'Sending',
    sent: 'Sent',
    failed: 'Failed',
    paused: 'Paused',
}

export const CHANNEL_LABEL: Record<Channel, string> = { email: 'Email', sms: 'SMS', push: 'Push' }

// 30 days of message counts per messaging type and channel, for the overview's performance numbers.
export interface TypeSeries {
    kind: EntryKind
    channel: Channel
    sent: number[]
    openRate: number
    clickRate: number
    deliveredRate: number
}

function series(base: number, spread: number, seed: number, spikes: Record<number, number> = {}): number[] {
    return Array.from({ length: 30 }, (_, i) => {
        const d = TODAY.subtract(29 - i, 'day')
        const weekend = d.day() === 0 || d.day() === 6
        return Math.round((base + noise(seed + i) * spread) * (weekend ? 0.6 : 1) + (spikes[i] ?? 0))
    })
}

export const SERIES: TypeSeries[] = [
    {
        kind: 'broadcast',
        channel: 'email',
        sent: series(0, 0, 1, { 11: 12480, 20: 3210, 28: 1204 }),
        openRate: 0.44,
        clickRate: 0.08,
        deliveredRate: 0.981,
    },
    {
        kind: 'workflow',
        channel: 'email',
        sent: series(1150, 500, 2, { 25: 960 }),
        openRate: 0.39,
        clickRate: 0.07,
        deliveredRate: 0.986,
    },
    {
        kind: 'transactional',
        channel: 'email',
        sent: series(1100, 400, 3),
        openRate: 0.71,
        clickRate: 0.52,
        deliveredRate: 0.995,
    },
    {
        kind: 'broadcast',
        channel: 'push',
        sent: series(0, 0, 4, { 27: 7400 }),
        openRate: 0.12,
        clickRate: 0.04,
        deliveredRate: 0.93,
    },
    { kind: 'workflow', channel: 'sms', sent: series(70, 30, 5), openRate: 0, clickRate: 0.09, deliveredRate: 0.97 },
    { kind: 'broadcast', channel: 'sms', sent: series(0, 0, 6), openRate: 0, clickRate: 0, deliveredRate: 0 },
    { kind: 'workflow', channel: 'push', sent: series(0, 0, 7), openRate: 0, clickRate: 0, deliveredRate: 0 },
    { kind: 'transactional', channel: 'sms', sent: series(0, 0, 8), openRate: 0, clickRate: 0, deliveredRate: 0 },
    { kind: 'transactional', channel: 'push', sent: series(0, 0, 9), openRate: 0, clickRate: 0, deliveredRate: 0 },
]

export const SERIES_LABELS = Array.from({ length: 30 }, (_, i) => TODAY.subtract(29 - i, 'day').format('YYYY-MM-DD'))

export function sum(values: number[]): number {
    return values.reduce((total, value) => total + value, 0)
}

export function formatCount(value: number): string {
    return value >= 10000 ? `${(value / 1000).toFixed(1)}k` : value.toLocaleString('en-US')
}

export function percent(value: number): string {
    return `${(value * 100).toFixed(value < 0.1 ? 1 : 0)}%`
}

/** What went out, newest first, for the timeline overview. */
export interface ActivityItem {
    id: string
    at: dayjs.Dayjs
    text: string
    detail?: string
    tone: 'default' | 'success' | 'warning' | 'destructive'
    entryId?: string
}

export const ACTIVITY: ActivityItem[] = [
    {
        id: 'a1',
        at: dayjs().subtract(25, 'minute'),
        text: 'Trial ending reminder sent to 132 people',
        detail: '38 SMS messages failed: numbers rejected by the carrier',
        tone: 'warning',
    },
    {
        id: 'a2',
        at: dayjs().subtract(3, 'hour'),
        text: 'Robin Example scheduled Black Friday early access',
        detail: 'Goes out in 2 days to 18,900 people',
        tone: 'default',
        entryId: 'b-bf',
    },
    {
        id: 'a3',
        at: day(-1, 14, 20),
        text: 'Pricing page survey stopped after 1,204 of 5,000 messages',
        detail: 'mail.example.com failed its DKIM check',
        tone: 'destructive',
        entryId: 'b-survey',
    },
    {
        id: 'a4',
        at: day(-2, 18, 5),
        text: 'Mobile app release note pushed to 7,400 devices',
        detail: '12% opened',
        tone: 'success',
        entryId: 'p-release',
    },
    {
        id: 'a5',
        at: day(-4, 11, 2),
        text: 'Beta invite, wave 2 sent to 960 people',
        detail: '61% opened, 24% clicked',
        tone: 'success',
        entryId: 'w-beta',
    },
    {
        id: 'a6',
        at: day(-5, 9, 40),
        text: 'Sam Example edited the Receipt template',
        tone: 'default',
    },
]

export const SENDING_DOMAIN = 'mail.example.com'
