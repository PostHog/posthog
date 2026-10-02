import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { sessionFrameResponse } from '~/mocks/fixtures/sessionFrame'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { recordingTimeline, timelineRows } from '../utils/recordingTimeline'
import { RecordingTimeline } from './RecordingTimeline'

const MIN = 60_000
let nextId = 1
const id = (): string => `0198f2a1-0000-7000-8000-${String(nextId++).padStart(12, '0')}`

interface ChapterSpec {
    start: number
    end: number
    title: string
    frame?: boolean
}

function summary({
    chapters = [],
    inactive = [],
    status = 'succeeded',
    legacyIdle = false,
}: {
    chapters?: ChapterSpec[]
    inactive?: [number, number][]
    status?: ReplayObservationApi['status']
    legacyIdle?: boolean
}): ReplayObservationApi {
    const output: Record<string, unknown> = {
        scanner_type: 'summarizer',
        title: 'Session summary',
        summary: '',
        confidence: 0.8,
        chapters: chapters.map((c) => ({
            kind: 'activity',
            start_ms: c.start,
            end_ms: c.end,
            title: c.title,
            thumbnail_ms: Math.round((c.start + c.end) / 2),
        })),
    }
    if (legacyIdle) {
        output.chapters = (output.chapters as Record<string, unknown>[]).flatMap((c, i) =>
            i === 0 ? [c] : [{ kind: 'idle', start_ms: c.start_ms, end_ms: c.start_ms, title: 'Idle' }, c]
        )
    } else {
        output.inactive_periods = inactive.map(([start, end]) => ({ start_ms: start, end_ms: end }))
    }
    return {
        id: id(),
        session_id: 'session-1',
        status,
        created_at: '2026-10-02T09:00:00Z',
        scanner_origin: 'inline',
        scanner_snapshot: { name: 'Quick summary', scanner_type: 'summarizer', scanner_config: {} },
        scanner_result: status === 'succeeded' ? { model_output: output } : null,
        media: chapters.flatMap((c, position) =>
            c.frame === false ? [] : [{ id: id(), kind: 'chapter', position, asset_id: 1 }]
        ),
    } as unknown as ReplayObservationApi
}

function scan(
    scannerType: 'monitor' | 'scorer' | 'classifier',
    name: string,
    keyMomentMs: number | null,
    answer: Record<string, unknown>
): ReplayObservationApi {
    return {
        id: id(),
        session_id: 'session-1',
        status: 'succeeded',
        created_at: '2026-10-02T09:05:00Z',
        scanner_origin: 'configured',
        scanner_snapshot: { name, scanner_type: scannerType, scanner_config: {} },
        scanner_result: {
            model_output: { scanner_type: scannerType, confidence: 0.8, key_moment_ms: keyMomentMs, ...answer },
        },
        media: [],
    } as unknown as ReplayObservationApi
}

const checkoutMonitor = (at: number | null): ReplayObservationApi =>
    scan('monitor', 'Struggled at checkout', at, { verdict: 'yes', reasoning: '' })
const frustrationScorer = (at: number | null): ReplayObservationApi =>
    scan('scorer', 'Frustration', at, { score: 4, reasoning: '' })
const intentClassifier = (at: number | null): ReplayObservationApi =>
    scan('classifier', 'Visit intent', at, { tags: ['Pricing research'], reasoning: '' })
const rageMonitor = (at: number | null): ReplayObservationApi =>
    scan('monitor', 'Rage clicks', at, { verdict: 'no', reasoning: '' })

const SHORT = [
    { start: 0, end: 18_000, title: 'Browses surveys product page' },
    { start: 18_000, end: 39_000, title: 'Reviews survey use cases table' },
    { start: 39_000, end: 61_000, title: 'Opens install with AI prompt' },
]

const MEDIUM = [
    { start: 0, end: 52_000, title: 'Searches for winter jackets' },
    { start: 52_000, end: 118_000, title: 'Compares three parka product pages' },
    { start: 131_000, end: 176_000, title: 'Adds insulated parka to cart' },
    { start: 176_000, end: 214_000, title: 'Applies discount code at checkout' },
    { start: 214_000, end: 236_000, title: 'Payment form rejects card' },
    { start: 236_000, end: 291_000, title: 'Retries payment with a second card' },
]
const MEDIUM_INACTIVE: [number, number][] = [
    [118_000, 131_000],
    [140_000, 146_000],
]

const LONG: ChapterSpec[] = [
    { start: 0, end: 3 * MIN, title: 'Signs in and opens the dashboard' },
    { start: 3 * MIN, end: 7 * MIN, title: 'Filters revenue report by region' },
    { start: 17 * MIN, end: 21 * MIN, title: 'Exports quarterly revenue to CSV' },
    { start: 21 * MIN, end: 34 * MIN, title: 'Edits invoice line items' },
    { start: 44 * MIN, end: 47 * MIN, title: 'Opens billing settings' },
    { start: 47 * MIN, end: 52 * MIN, title: 'Updates payment method details' },
    { start: 52 * MIN, end: 58 * MIN, title: 'Invites a teammate to the workspace' },
]
const LONG_INACTIVE: [number, number][] = [
    [7 * MIN, 17 * MIN],
    [25 * MIN, 31 * MIN],
    [34 * MIN, 44 * MIN],
    [58 * MIN, 61 * MIN],
]

const VERY_LONG: ChapterSpec[] = Array.from({ length: 20 }, (_, i) => ({
    start: i * 9 * MIN,
    end: i * 9 * MIN + 6 * MIN,
    title: [
        'Triages alerts on the sensor dashboard',
        'Acknowledges the cooling unit alert',
        'Reviews sensor history for unit 4',
        'Opens the maintenance ticket form',
        'Assigns the ticket to the on-call engineer',
    ][i % 5],
}))
const VERY_LONG_INACTIVE: [number, number][] = VERY_LONG.map((c) => [c.end, c.end + 3 * MIN])

const meta: Meta<typeof RecordingTimeline> = {
    title: 'Scenes-App/Replay Vision/RecordingTimeline',
    component: RecordingTimeline,
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/vision/observations/:id/thumbnail/': () => sessionFrameResponse() },
        }),
        (Story) => (
            <div className="w-[420px] border rounded bg-surface-primary">
                <Story />
            </div>
        ),
    ],
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export default meta

type Story = StoryObj<{ observations: ReplayObservationApi[]; currentTimeMs?: number }>

const render: Story['render'] = ({ observations, currentTimeMs = 0 }) => {
    const timeline = recordingTimeline(observations)
    return (
        <RecordingTimeline
            timeline={timeline}
            rows={timelineRows(timeline)}
            currentTimeMs={currentTimeMs}
            onSeek={() => {}}
            onMarkerClick={() => {}}
            onSummarize={() => {}}
            summarizing={false}
            onRebuild={() => {}}
            rebuilding={false}
        />
    )
}

export const OneScanNoSummary: Story = {
    render,
    args: { observations: [checkoutMonitor(214_000)] },
}

export const SeveralScansNoSummary: Story = {
    render,
    args: {
        observations: [
            checkoutMonitor(214_000),
            frustrationScorer(236_000),
            intentClassifier(60_000),
            rageMonitor(null),
        ],
    },
}

export const SummaryInProgress: Story = {
    render,
    args: { observations: [summary({ status: 'running' }), checkoutMonitor(214_000)] },
}

export const SummaryFromBeforeBreakdowns: Story = {
    render,
    args: { observations: [summary({}), checkoutMonitor(214_000)] },
}

export const ShortRecordingSummaryOnly: Story = {
    render,
    args: { observations: [summary({ chapters: SHORT })], currentTimeMs: 25_000 },
}

export const MediumRecordingWithScans: Story = {
    render,
    args: {
        observations: [
            summary({ chapters: MEDIUM, inactive: MEDIUM_INACTIVE }),
            checkoutMonitor(221_000),
            frustrationScorer(240_000),
            intentClassifier(60_000),
        ],
        currentTimeMs: 225_000,
    },
}

export const LongRecordingWithIdleGaps: Story = {
    render,
    args: {
        observations: [summary({ chapters: LONG, inactive: LONG_INACTIVE }), checkoutMonitor(50 * MIN)],
        currentTimeMs: 12 * MIN,
    },
}

export const VeryLongRecording: Story = {
    render,
    args: {
        observations: [summary({ chapters: VERY_LONG, inactive: VERY_LONG_INACTIVE }), frustrationScorer(95 * MIN)],
        currentTimeMs: 100 * MIN,
    },
}

export const KeyMomentDuringIdle: Story = {
    render,
    args: {
        observations: [summary({ chapters: LONG, inactive: LONG_INACTIVE }), rageMonitor(10 * MIN)],
    },
}

export const ChaptersWithoutFrames: Story = {
    render,
    args: {
        observations: [summary({ chapters: MEDIUM.map((c) => ({ ...c, frame: false })), inactive: MEDIUM_INACTIVE })],
    },
}

export const SummaryWithIdleChaptersFromBeforeInactivePeriods: Story = {
    render,
    args: { observations: [summary({ chapters: MEDIUM, legacyIdle: true })] },
}
