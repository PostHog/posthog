import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { sessionFrameResponse } from '~/mocks/fixtures/sessionFrame'

import {
    LONG,
    LONG_INACTIVE,
    MEDIUM,
    MEDIUM_INACTIVE,
    MIN,
    SHORT,
    VERY_LONG,
    VERY_LONG_INACTIVE,
    checkoutMonitor,
    frustrationScorer,
    intentClassifier,
    summary,
} from '../__mocks__/recordingTimelineObservations'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { recordingTimeline, timelineRows } from '../utils/recordingTimeline'
import { RecordingTimeline } from './RecordingTimeline'

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

type Story = StoryObj<{ observations: ReplayObservationApi[]; currentTimeMs?: number; durationMs?: number }>

const render: Story['render'] = ({ observations, currentTimeMs = 0, durationMs }) => {
    const timeline = recordingTimeline(observations)
    durationMs ??= Math.max(5 * MIN, ...timeline.chapters.map((c) => c.endMs))
    return (
        <RecordingTimeline
            timeline={timeline}
            rows={timelineRows(timeline, durationMs)}
            currentTimeMs={currentTimeMs}
            onSeek={() => {}}
            onSummarize={() => {}}
            summarizing={false}
        />
    )
}

export const OneScanNoSummary: Story = {
    render,
    args: { observations: [checkoutMonitor(214_000)] },
}

export const SummaryInProgress: Story = {
    render,
    args: { observations: [summary({ status: 'running' }), checkoutMonitor(214_000)] },
}

export const SummaryFromBeforeTimelines: Story = {
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
