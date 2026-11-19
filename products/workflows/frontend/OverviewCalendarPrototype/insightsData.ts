// PROTOTYPE (throwaway): invented data for overview B2, the performance page with insights. Nothing here is real.
import type { SankeyLinkInput, SankeyNodeInput } from '@posthog/quill-charts'

import { EntryKind, SERIES, TODAY, TypeSeries, sum } from './prototypeData'

export type ChannelFilter = 'all' | 'email' | 'sms' | 'push'

export function seriesFor(channel: ChannelFilter): TypeSeries[] {
    return SERIES.filter((s) => channel === 'all' || s.channel === channel)
}

export function dailyTotals(rows: TypeSeries[]): number[] {
    return Array.from({ length: 30 }, (_, i) => sum(rows.map((row) => row.sent[i] ?? 0)))
}

export function weightedRate(rows: TypeSeries[], pick: (row: TypeSeries) => number): number {
    const sent = sum(rows.map((row) => sum(row.sent)))
    return sent ? sum(rows.map((row) => sum(row.sent) * pick(row))) / sent : 0
}

// Share of clicks that end in the goal event within 7 days, per channel.
export const CONVERSION_RATE: Record<ChannelFilter, number> = { all: 0.09, email: 0.091, sms: 0.12, push: 0.05 }

export const CONVERSIONS_SERIES = Array.from({ length: 30 }, (_, i) => Math.round(48 + 20 * Math.sin(i / 3) + i * 0.8))

// Email opens by weekday and hour, Monday first.
export const SEND_TIME_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
export const SEND_TIME_HOURS = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}:00`)
export const SEND_TIME_OPENS = SEND_TIME_DAYS.map((_, day) =>
    SEND_TIME_HOURS.map((_, hour) => {
        const morning = Math.exp(-((hour - 9) ** 2) / 6)
        const evening = 0.55 * Math.exp(-((hour - 20) ** 2) / 5)
        const weekday = day < 5 ? 1 : 0.45
        const tuesday = day === 1 ? 1.25 : 1
        return Math.round(40 + 900 * (morning + evening) * weekday * tuesday)
    })
)

export const AFTER_CLICK_STAGES = ['Clicked', 'Landed on', 'Within 7 days']

export const AFTER_CLICK_NODES: SankeyNodeInput[] = [
    { id: 'clicked', label: 'Clicked a link' },
    { id: 'pricing', label: 'Pricing page' },
    { id: 'dashboard', label: 'A dashboard' },
    { id: 'docs', label: 'Docs' },
    { id: 'signup', label: 'Sign-up' },
    { id: 'upgraded', label: 'Upgraded', color: 'var(--data-color-3)' },
    { id: 'trial', label: 'Started a trial', color: 'var(--data-color-1)' },
    { id: 'returned', label: 'Came back', color: 'var(--data-color-7)' },
    { id: 'left', label: 'Did not return', color: 'var(--data-color-10)' },
]

export const AFTER_CLICK_LINKS: SankeyLinkInput[] = [
    { source: 'clicked', target: 'dashboard', value: 7400 },
    { source: 'clicked', target: 'pricing', value: 6200 },
    { source: 'clicked', target: 'docs', value: 5100 },
    { source: 'clicked', target: 'signup', value: 2760 },
    { source: 'pricing', target: 'upgraded', value: 980 },
    { source: 'pricing', target: 'trial', value: 1400 },
    { source: 'pricing', target: 'returned', value: 1900 },
    { source: 'pricing', target: 'left', value: 1920 },
    { source: 'dashboard', target: 'returned', value: 5300 },
    { source: 'dashboard', target: 'left', value: 2100 },
    { source: 'docs', target: 'returned', value: 2600 },
    { source: 'docs', target: 'left', value: 2500 },
    { source: 'signup', target: 'trial', value: 1900 },
    { source: 'signup', target: 'left', value: 860 },
]

export const TOP_MESSAGES = [
    { key: 'receipt', label: 'Receipt', clickRate: 0.52 },
    { key: 'webinar', label: 'Webinar invite: funnels in practice', clickRate: 0.11 },
    { key: 'trial', label: 'Trial ending reminder', clickRate: 0.094 },
    { key: 'october', label: 'October product update', clickRate: 0.08 },
    { key: 'digest', label: 'Weekly digest', clickRate: 0.061 },
]

export interface ScannerObservation {
    text: string
    sessions: number
    tone: 'positive' | 'negative' | 'neutral'
}

export interface ReplayScanner {
    name: string
    question: string
    sessions: number
    observations: ScannerObservation[]
}

export const SCANNER: ReplayScanner = {
    name: 'Checkout after Black Friday early access',
    question: 'Did people who clicked the email finish checkout, and where did they get stuck?',
    sessions: 214,
    observations: [
        { text: 'Most finished checkout in under 2 minutes', sessions: 122, tone: 'positive' },
        { text: 'The coupon field rejected the code on mobile', sessions: 31, tone: 'negative' },
        { text: 'People looked for annual pricing and did not find it', sessions: 18, tone: 'neutral' },
    ],
}

export const SUGGESTED_SCANNERS = [
    'Did trial ending reminders lead to a finished setup?',
    'What do people do after they open the weekly digest?',
]

// Round 3: the filter bar, conversion goals, suggestions and deliverability details.

export type Period = 7 | 30 | 90
export const PERIODS: { value: Period; label: string }[] = [
    { value: 7, label: 'Last 7 days' },
    { value: 30, label: 'Last 30 days' },
    { value: 90, label: 'Last 90 days' },
]

export type TopicKind = 'all' | 'marketing' | 'transactional'
export interface Topic {
    key: string
    label: string
    kind: Exclude<TopicKind, 'all'>
    share: number
}
export const TOPICS: Topic[] = [
    { key: 'product-updates', label: 'Product updates', kind: 'marketing', share: 0.4 },
    { key: 'newsletter', label: 'Newsletter', kind: 'marketing', share: 0.3 },
    { key: 'events', label: 'Events and webinars', kind: 'marketing', share: 0.2 },
    { key: 'offers', label: 'Offers', kind: 'marketing', share: 0.1 },
    { key: 'receipts', label: 'Receipts', kind: 'transactional', share: 0.5 },
    { key: 'account', label: 'Account and security', kind: 'transactional', share: 0.3 },
    { key: 'reminders', label: 'Reminders', kind: 'transactional', share: 0.2 },
]

export interface OverviewFilterState {
    period: Period
    topicKind: TopicKind
    topics: string[]
    channel: ChannelFilter
}
export const DEFAULT_OVERVIEW_FILTERS: OverviewFilterState = {
    period: 30,
    topicKind: 'all',
    topics: [],
    channel: 'all',
}

export function filteredRows(filters: OverviewFilterState): TypeSeries[] {
    return seriesFor(filters.channel).filter((row) =>
        filters.topicKind === 'all'
            ? true
            : filters.topicKind === 'transactional'
              ? row.kind === 'transactional'
              : row.kind !== 'transactional'
    )
}

// The share of the chosen kind's volume that the picked topics carry; 1 when no topic is picked.
export function topicFactor(filters: OverviewFilterState): number {
    const picked = TOPICS.filter((t) => filters.topics.includes(t.key))
    if (!picked.length) {
        return 1
    }
    const kinds = filters.topicKind === 'all' ? 2 : 1
    return Math.min(1, sum(picked.map((t) => t.share)) / kinds)
}

// Stretches or cuts a 30-day series to the period, oldest first.
export function forPeriod(data: number[], period: Period): number[] {
    if (period <= data.length) {
        return data.slice(-period)
    }
    return Array.from({ length: period }, (_, i) =>
        Math.round((data[i % data.length] ?? 0) * (0.8 + (0.2 * i) / period))
    )
}

export function periodLabels(period: Period): string[] {
    return Array.from({ length: period }, (_, i) => TODAY.subtract(period - 1 - i, 'day').format('YYYY-MM-DD'))
}

export interface ConversionGoal {
    key: string
    label: string
    factor: number
}
export const CONVERSION_GOALS: ConversionGoal[] = [
    { key: 'upgraded', label: 'Upgraded to a paid plan', factor: 1 },
    { key: 'signed-up', label: 'Signed up', factor: 1.6 },
    { key: 'dashboard', label: 'Created a dashboard', factor: 2.4 },
    { key: 'invited', label: 'Invited a teammate', factor: 0.7 },
]

export interface TopMessage {
    key: string
    label: string
    kind: EntryKind
    sent: number
    clickRate: number
}
export const TOP_MESSAGES_R3: TopMessage[] = [
    { key: 'receipt', label: 'Receipt', kind: 'transactional', sent: 21400, clickRate: 0.52 },
    { key: 'webinar', label: 'Webinar invite: funnels in practice', kind: 'broadcast', sent: 3210, clickRate: 0.11 },
    { key: 'trial', label: 'Trial ending reminder', kind: 'workflow', sent: 4180, clickRate: 0.094 },
    { key: 'october', label: 'October product update', kind: 'broadcast', sent: 12480, clickRate: 0.08 },
    { key: 'digest', label: 'Weekly digest', kind: 'workflow', sent: 16800, clickRate: 0.061 },
]

export interface Suggestion {
    key: string
    message: string
    title: string
    detail: string
    action: string
}
export const SUGGESTIONS: Suggestion[] = [
    {
        key: 'subject',
        message: 'Weekly digest',
        title: 'Test a shorter subject line',
        detail: 'Opens fell over the last 4 sends. A variant is drafted to try on half the recipients.',
        action: 'Review variant',
    },
    {
        key: 'timezone',
        message: 'Trial ending reminder',
        title: "Send in each person's time zone",
        detail: 'A third of recipients get it before 6:00 their time, and they open it least.',
        action: 'Review change',
    },
    {
        key: 'bounces',
        message: 'Re-engage dormant trials',
        title: 'Leave out addresses that bounced twice',
        detail: '412 addresses bounced on the last two sends and count against your bounce rate.',
        action: 'Review list',
    },
]

export const MAILBOX_PROVIDERS = [
    { key: 'gmail', label: 'Gmail', share: 0.46, delivered: 0.991, opened: 0.51 },
    { key: 'outlook', label: 'Outlook', share: 0.24, delivered: 0.962, opened: 0.38 },
    { key: 'apple', label: 'iCloud', share: 0.14, delivered: 0.988, opened: 0.62 },
    { key: 'yahoo', label: 'Yahoo', share: 0.08, delivered: 0.971, opened: 0.33 },
    { key: 'other', label: 'Other', share: 0.08, delivered: 0.979, opened: 0.41 },
]

export const DOMAIN_CHECKS = [
    { key: 'spf', label: 'SPF', ok: true },
    { key: 'dkim', label: 'DKIM', ok: false },
    { key: 'dmarc', label: 'DMARC', ok: true },
]

export const DAILY_LIMIT = { used: 12400, limit: 50000 }
