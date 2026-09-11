import type { Meta, StoryObj } from '@storybook/react'

import type {
    BarChartConfig,
    HeatmapConfig,
    Series,
    SlopeChartConfig,
    TimeSeriesBarChartConfig,
    TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'

import {
    type ReplayVisionScannerVisualizationExample,
    ReplayVisionVisualizationPrototype,
} from './ReplayVisionVisualizationPrototype'

const DATE_LABELS = [
    '2026-06-08',
    '2026-06-15',
    '2026-06-22',
    '2026-06-29',
    '2026-07-06',
    '2026-07-13',
    '2026-07-20',
    '2026-07-27',
    '2026-08-03',
    '2026-08-10',
    '2026-08-17',
    '2026-08-24',
]

const SHORT_DATE_LABELS = [
    'Jun 8',
    'Jun 15',
    'Jun 22',
    'Jun 29',
    'Jul 6',
    'Jul 13',
    'Jul 20',
    'Jul 27',
    'Aug 3',
    'Aug 10',
    'Aug 17',
    'Aug 24',
]

const LINE_CONFIG: TimeSeriesLineChartConfig = {
    xAxis: { timezone: 'UTC', interval: 'week' },
    yAxis: { format: 'short', showGrid: true },
    legend: { show: true, position: 'bottom' },
}

const PERCENT_LINE_CONFIG: TimeSeriesLineChartConfig = {
    xAxis: { timezone: 'UTC', interval: 'week' },
    yAxis: { format: 'numeric', suffix: '%', showGrid: true, min: 0 },
    legend: { show: true, position: 'bottom' },
}

const STACKED_BAR_CONFIG: TimeSeriesBarChartConfig = {
    barLayout: 'stacked',
    bandPadding: 0.24,
    xAxis: { timezone: 'UTC', interval: 'week' },
    yAxis: { format: 'short', showGrid: true },
    legend: { show: true, position: 'bottom' },
    tooltip: { showTotal: true, totalLabel: 'Scanned sessions' },
}

const SHARE_CONFIG: TimeSeriesBarChartConfig = {
    barLayout: 'percent',
    bandPadding: 0.24,
    xAxis: { timezone: 'UTC', interval: 'week' },
    yAxis: { format: 'percentage_scaled', showGrid: true },
    legend: { show: true, position: 'bottom' },
    tooltip: { showTotal: true, totalLabel: 'Observations' },
}

const HORIZONTAL_BAR_CONFIG: BarChartConfig = {
    axisOrientation: 'horizontal',
    showGrid: true,
    legend: { show: false },
}

const DISTRIBUTION_CONFIG: BarChartConfig = {
    showGrid: true,
    legend: { show: false },
}

const CHANGE_CONFIG: SlopeChartConfig = {
    showSeriesLabels: false,
    legend: { show: true, position: 'bottom' },
    valueFormatter: (value: number): string => `${value}%`,
    deltaFormatter: (delta: number): string => `${delta > 0 ? '+' : ''}${delta} points`,
}

const SHARE_HEATMAP_CONFIG: HeatmapConfig = {
    colorScale: 'linear',
    xTickFormatter: (label: string, index: number): string | null => (index % 2 === 0 ? label : null),
    tooltip: { valueFormatter: (value: number): string => `${value}% of observations` },
}

const COUNT_HEATMAP_CONFIG: HeatmapConfig = {
    colorScale: 'linear',
    xTickFormatter: (label: string, index: number): string | null => (index % 2 === 0 ? label : null),
    tooltip: { valueFormatter: (value: number): string => `${value} summaries` },
}

const MONITOR_TOTALS = [118, 124, 121, 132, 129, 141, 146, 150, 156, 162, 171, 168]
const MONITOR_MATCHES = [9, 9, 11, 15, 13, 17, 20, 19, 24, 28, 31, 27]
const MONITOR_CLEAR = MONITOR_TOTALS.map((total, index) => total - MONITOR_MATCHES[index])
const MONITOR_RATE = MONITOR_TOTALS.map((total, index) => Math.round((MONITOR_MATCHES[index] / total) * 1000) / 10)

const CLASSIFIER_SERIES: Series[] = [
    {
        key: 'investigate-incidents',
        label: 'Investigate incidents',
        data: [42, 40, 39, 38, 37, 35, 33, 32, 31, 30, 29, 28],
        fill: { opacity: 0.45 },
    },
    {
        key: 'monitor-health',
        label: 'Monitor service health',
        data: [25, 27, 28, 29, 30, 30, 31, 31, 32, 31, 30, 29],
        fill: { opacity: 0.45 },
    },
    {
        key: 'compare-releases',
        label: 'Compare releases',
        data: [8, 9, 10, 10, 12, 13, 15, 17, 19, 21, 23, 24],
        fill: { opacity: 0.45 },
    },
    {
        key: 'configure-alerts',
        label: 'Configure alerts',
        data: [10, 11, 10, 11, 10, 11, 10, 11, 10, 10, 9, 10],
        fill: { opacity: 0.45 },
    },
    {
        key: 'share-reports',
        label: 'Share status reports',
        data: [12, 14, 14, 15, 15, 16, 16, 16, 15, 15, 14, 13],
        fill: { opacity: 0.45 },
    },
    {
        key: 'automate-triage',
        label: 'Automate triage',
        data: [0, 0, 0, 0, 0, 2, 4, 7, 11, 15, 18, 22],
        fill: { opacity: 0.45 },
    },
    {
        key: 'inconclusive',
        label: 'Inconclusive',
        data: [5, 4, 5, 4, 5, 5, 5, 5, 5, 5, 5, 4],
        fill: { opacity: 0.45 },
    },
]

const CLASSIFIER_CHANGE_SERIES: Series[] = [
    { key: 'investigate-incidents', label: 'Investigate incidents', data: [30, 23] },
    { key: 'monitor-health', label: 'Monitor service health', data: [27, 24] },
    { key: 'compare-releases', label: 'Compare releases', data: [13, 17] },
    { key: 'configure-alerts', label: 'Configure alerts', data: [9, 8] },
    { key: 'share-reports', label: 'Share status reports', data: [14, 11] },
    { key: 'automate-triage', label: 'Automate triage', data: [3, 13] },
    { key: 'inconclusive', label: 'Inconclusive', data: [4, 4] },
]

const CLASSIFIER_TOTALS = DATE_LABELS.map((_, index) =>
    CLASSIFIER_SERIES.reduce((total, series) => total + (series.data[index] ?? 0), 0)
)
const CLASSIFIER_TIMELINE_SERIES = [...CLASSIFIER_SERIES].reverse()
const CLASSIFIER_TIMELINE_CELLS = CLASSIFIER_TIMELINE_SERIES.map((series) =>
    series.data.map((count, index) => Math.round((count / CLASSIFIER_TOTALS[index]) * 100))
)

const SCORER_TREND_SERIES: Series[] = [
    { key: 'median', label: 'Median', data: [2.8, 2.7, 3, 3.1, 3, 3.3, 3.5, 3.6, 3.9, 4.1, 4.4, 4.2] },
    { key: 'p90', label: '90th percentile', data: [6.2, 6, 6.4, 6.5, 6.6, 6.9, 7.2, 7.4, 7.8, 8.1, 8.4, 8.2] },
    { key: 'average', label: 'Average', data: [3.2, 3.1, 3.3, 3.4, 3.4, 3.6, 3.8, 3.9, 4.2, 4.4, 4.7, 4.5] },
]

const SCORER_BAND_SERIES: Series[] = [
    { key: 'smooth', label: 'Smooth (0 to 3)', data: [78, 82, 76, 79, 75, 72, 68, 65, 61, 57, 52, 55] },
    {
        key: 'friction',
        label: 'Some friction (4 to 6)',
        data: [31, 30, 34, 35, 38, 42, 45, 48, 51, 55, 59, 57],
    },
    {
        key: 'high-friction',
        label: 'High friction (7 to 10)',
        data: [9, 8, 11, 12, 13, 16, 19, 22, 27, 31, 38, 34],
    },
]

const SUMMARY_THEME_LABELS = ['exports', 'billing', 'filters', 'checkout', 'automation']
const SUMMARY_THEME_CELLS = [
    [18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7],
    [8, 9, 8, 10, 9, 11, 10, 12, 11, 10, 11, 10],
    [12, 13, 14, 15, 14, 16, 17, 18, 19, 20, 20, 21],
    [19, 18, 20, 21, 23, 24, 24, 25, 27, 29, 31, 30],
    [0, 0, 0, 0, 1, 2, 4, 7, 9, 13, 17, 20],
]

const EXAMPLES: ReplayVisionScannerVisualizationExample[] = [
    {
        key: 'dead-ends',
        scannerType: 'monitor',
        name: 'Dead-end pages',
        description: 'Detect sessions where a user gets stuck with no clear next action.',
        observationCount: 1718,
        outputLabel: 'yes or no verdict',
        views: [
            {
                key: 'rate',
                label: 'Rate',
                tooltip: 'How often the scanner detected a dead end',
                description: 'The detection rate separates a changing problem from changes in scan volume.',
                callout: 'Dead-end rate peaked at 18.1%',
                chart: {
                    kind: 'time-series-line',
                    labels: DATE_LABELS,
                    series: [{ key: 'dead-end-rate', label: 'Dead-end rate', data: MONITOR_RATE }],
                    config: PERCENT_LINE_CONFIG,
                },
            },
            {
                key: 'volume',
                label: 'Volume',
                tooltip: 'How many sessions matched or did not match each week',
                description: 'Stacked counts show detections in the context of every scanned session.',
                callout: 'Weekly detections rose from 9 to 27',
                chart: {
                    kind: 'time-series-bar',
                    labels: DATE_LABELS,
                    series: [
                        { key: 'dead-end', label: 'Dead end detected', data: MONITOR_MATCHES },
                        { key: 'clear', label: 'No dead end', data: MONITOR_CLEAR },
                    ],
                    config: STACKED_BAR_CONFIG,
                },
            },
        ],
    },
    {
        key: 'user-intent',
        scannerType: 'classifier',
        name: 'User intent',
        description: 'Classify what each user appeared to be trying to accomplish.',
        observationCount: 1383,
        outputLabel: 'configured and freeform categories',
        views: [
            {
                key: 'volume',
                label: 'Volume',
                tooltip: 'How many sessions appeared in each category each week',
                description: 'Weekly counts show category growth alongside changes in scanner volume.',
                callout: 'Automate triage first appeared Jul 13',
                chart: {
                    kind: 'time-series-line',
                    labels: DATE_LABELS,
                    series: CLASSIFIER_SERIES,
                    config: LINE_CONFIG,
                },
            },
            {
                key: 'share',
                label: 'Share',
                tooltip: 'How categories contribute to weekly assignments',
                description: 'Each week is normalized to 100% so scanner volume does not affect the category mix.',
                callout: 'Automate triage reached 17% of assignments',
                chart: {
                    kind: 'time-series-bar',
                    labels: DATE_LABELS,
                    series: CLASSIFIER_SERIES,
                    config: SHARE_CONFIG,
                },
            },
            {
                key: 'movement',
                label: 'Movement',
                tooltip: 'Which categories gained or lost share between two periods',
                description: 'A two-period comparison makes category movement and rank changes easier to scan.',
                callout: 'Automate triage gained 10 points',
                chart: {
                    kind: 'slope',
                    labels: ['Previous 4 weeks', 'Current 4 weeks'],
                    series: CLASSIFIER_CHANGE_SERIES,
                    config: CHANGE_CONFIG,
                },
            },
            {
                key: 'emergence',
                label: 'Emergence',
                tooltip: 'When categories appeared, persisted, or faded',
                description: 'Color intensity shows categories appearing, persisting, and fading across the range.',
                callout: 'Automate triage is a new freeform category',
                chart: {
                    kind: 'heatmap',
                    xLabels: SHORT_DATE_LABELS,
                    yLabels: CLASSIFIER_TIMELINE_SERIES.map((series) => series.label),
                    cells: CLASSIFIER_TIMELINE_CELLS,
                    config: SHARE_HEATMAP_CONFIG,
                },
            },
        ],
    },
    {
        key: 'frustration-score',
        scannerType: 'scorer',
        name: 'Frustration score',
        description: 'Score visible friction in each session from 0 to 10.',
        observationCount: 1585,
        outputLabel: 'numeric score',
        views: [
            {
                key: 'trend',
                label: 'Trend',
                tooltip: 'How typical and high-friction scores changed',
                description: 'Median, average, and high-end scores distinguish broad shifts from isolated sessions.',
                callout: 'Median frustration rose from 2.8 to 4.2',
                chart: {
                    kind: 'time-series-line',
                    labels: DATE_LABELS,
                    series: SCORER_TREND_SERIES,
                    config: { ...LINE_CONFIG, yAxis: { format: 'numeric', min: 0, max: 10, showGrid: true } },
                },
            },
            {
                key: 'distribution',
                label: 'Distribution',
                tooltip: 'Where scores landed across the configured scale',
                description:
                    'The full distribution shows whether the average represents most sessions or hides two groups.',
                callout: 'Scores cluster at 3 and 7',
                chart: {
                    kind: 'bar',
                    labels: ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10'],
                    series: [
                        {
                            key: 'sessions',
                            label: 'Sessions',
                            data: [34, 67, 137, 261, 215, 177, 167, 234, 160, 90, 43],
                        },
                    ],
                    config: DISTRIBUTION_CONFIG,
                },
            },
            {
                key: 'bands',
                label: 'Bands',
                tooltip: 'How the share of smooth and frustrating sessions changed',
                description: 'Score bands turn a numeric scale into an outcome mix that is easier to monitor.',
                callout: 'High-friction sessions reached 25% of scores',
                chart: {
                    kind: 'time-series-bar',
                    labels: DATE_LABELS,
                    series: SCORER_BAND_SERIES,
                    config: SHARE_CONFIG,
                },
            },
        ],
    },
    {
        key: 'session-summary',
        scannerType: 'summarizer',
        name: 'Session summary',
        description: 'Summarize what happened and extract friction points and keywords.',
        observationCount: 1248,
        outputLabel: 'summary facets and keywords',
        views: [
            {
                key: 'friction-rate',
                label: 'Friction rate',
                tooltip: 'How often summaries reported at least one friction point',
                description:
                    'The rate turns open-ended summaries into a stable signal without discarding their detail.',
                callout: 'Friction appeared in 31% of recent summaries',
                chart: {
                    kind: 'time-series-line',
                    labels: DATE_LABELS,
                    series: [
                        {
                            key: 'friction-rate',
                            label: 'Summaries with friction',
                            data: [18, 17, 19, 20, 21, 22, 24, 23, 26, 28, 31, 30],
                        },
                    ],
                    config: PERCENT_LINE_CONFIG,
                },
            },
            {
                key: 'friction-points',
                label: 'Friction points',
                tooltip: 'Which friction points appeared most often',
                description: 'Ranked phrases preserve what the scanner saw while making repeated problems visible.',
                callout: 'Checkout stalls appear in 74 summaries',
                chart: {
                    kind: 'bar',
                    labels: [
                        'Checkout stalls after payment',
                        'Filters reset unexpectedly',
                        'Export progress is unclear',
                        'Billing language is confusing',
                        'Automation setup has no feedback',
                    ],
                    series: [{ key: 'summaries', label: 'Summaries', data: [74, 61, 48, 37, 29] }],
                    config: HORIZONTAL_BAR_CONFIG,
                },
            },
            {
                key: 'keywords',
                label: 'Keywords',
                tooltip: 'When summary keywords appeared or faded',
                description:
                    'A keyword timeline makes shifts in open-ended session summaries visible without fixed categories.',
                callout: 'Automation emerged as a recurring keyword',
                chart: {
                    kind: 'heatmap',
                    xLabels: SHORT_DATE_LABELS,
                    yLabels: SUMMARY_THEME_LABELS,
                    cells: SUMMARY_THEME_CELLS,
                    config: COUNT_HEATMAP_CONFIG,
                },
            },
        ],
    },
]

const meta: Meta<typeof ReplayVisionVisualizationPrototype> = {
    title: 'Replay Vision/Explorations/Scanner visualization examples',
    component: ReplayVisionVisualizationPrototype,
    decorators: [
        (Story) => (
            <div className="min-h-screen bg-bg-light p-6">
                <Story />
            </div>
        ),
    ],
    parameters: { layout: 'fullscreen' },
    args: {
        initialScannerKey: 'dead-ends',
        examples: EXAMPLES,
    },
}

export default meta

type Story = StoryObj<typeof ReplayVisionVisualizationPrototype>

export const AllScannerTypes: Story = {}

export const Classifier: Story = { args: { initialScannerKey: 'user-intent' } }

export const Scorer: Story = { args: { initialScannerKey: 'frustration-score' } }

export const Summarizer: Story = { args: { initialScannerKey: 'session-summary' } }
