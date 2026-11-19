// PROTOTYPE (throwaway): invented data for overview B2, the performance page with insights. Nothing here is real.
import type { SankeyLinkInput, SankeyNodeInput } from '@posthog/quill-charts'

import { SERIES, TypeSeries, sum } from './prototypeData'

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
