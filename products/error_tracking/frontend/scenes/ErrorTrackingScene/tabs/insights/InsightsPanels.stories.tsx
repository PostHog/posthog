import { Meta, StoryObj } from '@storybook/react'

import { type ChartTheme } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'

import { ExceptionBandChart } from './ExceptionBandChart'
import { ExceptionBandTable } from './ExceptionBandTable'
import { InsightMetric, InsightsMetrics } from './insightsMetrics'
import { MetricTiles } from './MetricTiles'
import { buildAppBreakdown, buildReleaseBreakdown, parseReleaseRows } from './releaseBreakdown'

const BUCKETS = [
    '2026-06-01 00:00:00',
    '2026-06-02 00:00:00',
    '2026-06-03 00:00:00',
    '2026-06-04 00:00:00',
    '2026-06-05 00:00:00',
    '2026-06-06 00:00:00',
    '2026-06-07 00:00:00',
]
const LABELS = ['Jun 1', 'Jun 2', 'Jun 3', 'Jun 4', 'Jun 5', 'Jun 6', 'Jun 7']

function metric(
    value: number,
    previousValue: number,
    sparkline: number[],
    goodDirection: 'up' | 'down'
): InsightMetric {
    return {
        value,
        previousValue,
        deltaPct: previousValue ? ((value - previousValue) / previousValue) * 100 : null,
        sparkline,
        sparklineLabels: LABELS,
        goodDirection,
    }
}

const METRICS: InsightsMetrics = {
    exceptions: metric(18420, 21030, [2900, 2740, 2610, 2580, 2490, 2380, 2720], 'down'),
    affectedUsers: metric(1840, 1655, [280, 265, 250, 244, 238, 231, 332], 'down'),
    sessions: metric(96200, 88400, [13100, 13500, 13800, 13600, 14100, 14000, 14100], 'up'),
    crashSessions: metric(4210, 5120, [640, 620, 600, 590, 580, 570, 610], 'down'),
    crashFreeRate: metric(95.6, 94.2, [95.1, 95.4, 95.7, 95.7, 95.9, 95.9, 95.7], 'up'),
    releases: metric(4, 2, [2, 2, 3, 3, 4, 4, 4], 'up'),
}

// A window that ends mid-period: the last bucket's counts sit far below its neighbours because the
// interval has not finished. Both stories exist to show that reads as in-progress, not as a drop.
const PARTIAL_TAIL: InsightsMetrics = {
    ...METRICS,
    exceptions: metric(15980, 21030, [2900, 2740, 2610, 2580, 2490, 2380, 280], 'down'),
}

const RELEASE_ROWS = parseReleaseRows(
    [
        [
            'web',
            '2.4.0',
            '',
            [
                ['2026-06-05 00:00:00', 420],
                ['2026-06-06 00:00:00', 980],
                ['2026-06-07 00:00:00', 1240],
            ],
        ],
        [
            'web',
            '2.3.1',
            '',
            [
                ['2026-06-01 00:00:00', 1900],
                ['2026-06-02 00:00:00', 1780],
                ['2026-06-03 00:00:00', 1710],
                ['2026-06-04 00:00:00', 1650],
                ['2026-06-05 00:00:00', 900],
            ],
        ],
        [
            'ios',
            '4.1',
            '881',
            [
                ['2026-06-02 00:00:00', 320],
                ['2026-06-03 00:00:00', 300],
                ['2026-06-04 00:00:00', 280],
            ],
        ],
        ['web', '2.3.0', '', [['2026-06-01 00:00:00', 210]]],
        [
            '',
            '',
            '',
            [
                ['2026-06-01 00:00:00', 90],
                ['2026-06-06 00:00:00', 120],
            ],
        ],
    ],
    BUCKETS
)

const BREAKDOWN = buildReleaseBreakdown(RELEASE_ROWS, BUCKETS, buildTheme().colors)
const APP_BREAKDOWN = buildAppBreakdown(RELEASE_ROWS, BUCKETS, buildTheme().colors)

const meta: Meta = {
    title: 'Scenes-App/Error Tracking/Insights Panels',
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj

function withTheme(render: (theme: ChartTheme) => JSX.Element): () => JSX.Element {
    // Charts size themselves from their container via ResizeObserver, so the wrapper needs a definite
    // width. Without one the card collapses in the shrink-to-fit snapshot runtime.
    return () => <div className="w-[860px]">{render(buildTheme())}</div>
}

export const KeyMetrics: Story = {
    render: () => (
        <div className="w-[960px]">
            <MetricTiles metrics={METRICS} loading={false} incompleteTail={false} />
        </div>
    ),
}

export const KeyMetricsInProgressBucket: Story = {
    render: () => (
        <div className="w-[960px]">
            <MetricTiles metrics={PARTIAL_TAIL} loading={false} incompleteTail />
        </div>
    ),
}

export const KeyMetricsNarrowScene: Story = {
    render: () => (
        <div className="w-[520px]">
            <MetricTiles metrics={METRICS} loading={false} incompleteTail={false} />
        </div>
    ),
}

export const KeyMetricsLoading: Story = {
    // The point of this story is the skeletons, and the test runner treats a LemonSkeleton as a loader
    // it must see disappear before snapshotting. Tell it not to wait, or it times out on every run.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    render: () => (
        <div className="w-[960px]">
            <MetricTiles metrics={METRICS} loading incompleteTail={false} />
        </div>
    ),
}

export const ExceptionsByRelease: Story = {
    render: withTheme((theme) => (
        <ExceptionBandChart
            bands={BREAKDOWN.bands}
            labels={BUCKETS}
            loading={false}
            theme={theme}
            timezone="UTC"
            interval="day"
            incompleteTail={false}
            onSelectBand={() => {}}
        />
    )),
}

export const ExceptionsByApp: Story = {
    render: withTheme((theme) => (
        <ExceptionBandChart
            bands={APP_BREAKDOWN.bands}
            labels={BUCKETS}
            loading={false}
            theme={theme}
            timezone="UTC"
            interval="day"
            incompleteTail={false}
            onSelectBand={() => {}}
        />
    )),
}

export const ExceptionsByReleaseEmpty: Story = {
    render: withTheme((theme) => (
        <ExceptionBandChart
            bands={[]}
            labels={BUCKETS}
            loading={false}
            theme={theme}
            timezone="UTC"
            interval="day"
            incompleteTail={false}
            onSelectBand={() => {}}
        />
    )),
}

export const ReleaseList: Story = {
    render: withTheme(() => (
        <ExceptionBandTable bands={BREAKDOWN.bands} loading={false} columnLabel="Release" onSelectBand={() => {}} />
    )),
}

export const ExceptionsByReleaseInProgressBucket: Story = {
    render: withTheme((theme) => (
        <ExceptionBandChart
            bands={BREAKDOWN.bands}
            labels={BUCKETS}
            loading={false}
            theme={theme}
            timezone="UTC"
            interval="day"
            incompleteTail
            onSelectBand={() => {}}
        />
    )),
}
