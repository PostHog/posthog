import type { Meta, StoryFn, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import type { ReactElement, ReactNode } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { BarChart, DEFAULT_CHART_COLORS, type Series, TimeSeriesLineChart, useChartTheme } from '@posthog/quill-charts'

import {
    buildFunnelStepsBarConfig,
    buildSingleSeriesFunnelStepsBars,
    FUNNEL_STEPS_BAR_SERIES_KEY,
} from 'products/product_analytics/frontend/insights/funnels/shared/funnelStepsBarShared'

import { userEvent } from 'storybook/test'

import type { ExplainChartData } from './explainChartTypes'
import { ExplainChartView, type StoryEvidenceCharts } from './ExplainChartView'
import { isSeriesNamedIn } from './storyNamedSeries'

const VALUES = [
    58, 24, 22, 61, 64, 59, 63, 57, 26, 21, 60, 66, 62, 59, 498, 31, 23, 63, 58, 65, 61, 92, 41, 38, 95, 101, 97, 104,
    99, 18,
]
const DAYS = VALUES.map((_, index) => new Date(Date.UTC(2026, 8, 18 + index)).toISOString().slice(0, 10))
const SPIKE_INDEX = 14
const referrer = (index: number, name: string, typical: (value: number) => number, spike: number): Series => ({
    key: String(index),
    label: `signed_up - ${name}`,
    data: VALUES.map((value, day) => (day === SPIKE_INDEX ? spike : typical(value))),
    color: DEFAULT_CHART_COLORS[index],
})
const REFERRERS = ['news.example.com', '$direct', 'google.com']
const BY_REFERRER: Series[] = [
    referrer(0, REFERRERS[0]!, () => 3, 412),
    referrer(1, REFERRERS[1]!, (value) => Math.round(value * 0.55), 52),
    referrer(2, REFERRERS[2]!, (value) => Math.round(value * 0.4), 34),
]

const story: ExplainChartData = {
    shape: 'time_series',
    query: { kind: 'TrendsQuery', interval: 'day', series: [{ kind: 'EventsNode', event: 'signed_up' }] },
    results: [{ label: 'signed_up', data: VALUES, days: DAYS }],
    seriesIndex: 0,
    insightName: 'Sign-ups',
    lastPointInProgress: true,
    headline:
        'One article on **news.example.com** caused the spike, and sign-ups from **Canada** lifted the level since.',
    chapters: [
        {
            title: 'A spike on October 2',
            range: [14, 14],
            summary: 'One day stands far above the rest of the month, and the next day is back to normal.',
            cause: 'Almost all of the extra sign-ups came from **news.example.com** to the **/pricing** page. This looks like one article sending visitors, not a change in the product.',
            confidence: 'high',
            confidenceReason:
                'The referrer and the page both account for most of the day, and an annotation marks the article.',
            evidence: [
                {
                    text: '**news.example.com** sent 412 of the 498 sign-ups that day, against 3 on a typical day.',
                    url: 'https://us.posthog.com/project/1/insights/new',
                    query: {
                        kind: 'TrendsQuery',
                        series: [{ kind: 'EventsNode', event: 'signed_up' }],
                        breakdownFilter: { breakdown: '$referring_domain' },
                    },
                },
                { text: 'An annotation on October 2 reads "Launch article published".', url: null },
            ],
        },
        {
            title: 'Higher since October 9',
            range: [21, 28],
            summary: 'The level steps up and stays there.',
            cause: 'Most of the rise comes from **Canada**, which started the same week as the **French-language** signup page.',
            confidence: 'medium',
            confidenceReason: null,
            evidence: [
                {
                    text: 'Sign-ups from **Canada** went from 4 to 38 on a typical day.',
                    url: 'https://us.posthog.com/project/1/insights/new',
                },
            ],
        },
        {
            title: 'Today so far',
            range: [29, 29],
            summary: null,
            cause: null,
            confidence: null,
            confidenceReason: null,
            evidence: [],
        },
    ],
}

const SIGN_UPS: Series[] = [{ key: '0', label: 'signed_up', data: VALUES, color: DEFAULT_CHART_COLORS[0] }]
const CHART_CONFIG = { xAxis: { interval: 'day', timezone: 'UTC' } } as const

function StoryChart({ series, overlay }: { series: Series[]; overlay?: ReactNode }): ReactElement {
    const theme = useChartTheme()
    return (
        <div className="flex h-[260px] flex-col @3xl/story:h-[400px]">
            <TimeSeriesLineChart series={series} labels={DAYS} theme={theme} config={CHART_CONFIG}>
                {overlay}
            </TimeSeriesLineChart>
        </div>
    )
}

const FUNNEL_CHART_CONFIG = buildFunnelStepsBarConfig({ maxCategoryLabelWidth: 120, tooltipPlacement: 'cursor' })

const evidenceCharts: StoryEvidenceCharts = {
    canShow: (item) => !!item.query,
    prefetch: () => {},
    render: ({ text }) => (
        <StoryChart
            series={BY_REFERRER.map((item, index) =>
                isSeriesNamedIn([item.label, REFERRERS[index]!], text) ? item : { ...item, color: `${item.color}40` }
            )}
        />
    ),
}

const singleChapterStory: ExplainChartData = {
    ...story,
    headline: 'One article on **news.example.com** caused the spike.',
    chapters: story.chapters.slice(0, 1),
}

const FUNNEL_STEPS = [
    { name: 'Viewed pricing', count: 4210 },
    { name: 'Started signup', count: 1630 },
    { name: 'Verified email', count: 1490 },
    { name: 'Paid', count: 212 },
]

const funnelStory: ExplainChartData = {
    shape: 'funnel_steps',
    query: { kind: 'FunnelsQuery', series: [] },
    steps: FUNNEL_STEPS,
    breakdowns: [],
    seriesIndex: 0,
    insightName: 'Signup funnel',
    headline: 'Most people who verify their email never pay, since checkout moved to **annual plans only**.',
    chapters: [
        {
            title: 'Leaving the signup form',
            range: [1, 1],
            summary: 'Most visitors to the pricing page never start signing up, as in earlier months.',
            cause: 'This drop matches the months before, so nothing changed here.',
            confidence: 'high',
            confidenceReason: 'The share has held steady for six months.',
            evidence: [],
        },
        {
            title: 'The drop to paying',
            range: [2, 3],
            summary: 'Almost everyone who verifies their email leaves at checkout.',
            cause: 'Checkout started offering **annual plans only** in the same week, and the drop is in people who had picked a monthly plan.',
            confidence: 'medium',
            confidenceReason: 'The timing and the plan breakdown agree, with no other change that week.',
            evidence: [
                {
                    text: 'People who chose a **monthly** plan on the pricing page convert far less since the change.',
                    url: null,
                },
            ],
        },
    ],
}

function FunnelStoryChart({ overlay }: { overlay: ReactNode }): ReactElement {
    const theme = useChartTheme()
    const { series, labels, rows } = buildSingleSeriesFunnelStepsBars(FUNNEL_STEPS, { color: DEFAULT_CHART_COLORS[0]! })
    const config = { ...FUNNEL_CHART_CONFIG, xTickFormatter: (_: string, index: number) => rows[index]?.name ?? '' }
    return (
        <div className="flex h-[260px] flex-col @3xl/story:h-[400px]">
            <BarChart series={series} labels={labels} theme={theme} config={config}>
                {overlay}
            </BarChart>
        </div>
    )
}

const renderStory = (data: ExplainChartData = story): ReactElement => (
    <ExplainChartView
        data={data}
        renderChart={(overlay) => <StoryChart series={SIGN_UPS} overlay={overlay} />}
        openLink={() => {}}
        evidenceCharts={evidenceCharts}
    />
)

// The chart sizes its canvas off a ResizeObserver, so give it a definite width.
const width =
    (className: string) =>
    (Story: StoryFn): ReactElement => (
        <div className={className}>
            <Story />
        </div>
    )

// Opts the subtree into Quill's tokens, which the explanation reads directly as `var(--card)` and the like.
const quillTokens = (Story: StoryFn): ReactElement => (
    <div data-quill data-mcp-storybook>
        <Story />
    </div>
)

const meta: Meta = {
    title: 'MCP Apps/Explain Chart',
    decorators: [quillTokens, McpThemeDecorator],
    parameters: {
        mcpMaxWidth: 'none',
        testOptions: {
            // McpThemeDecorator has no dark mode, so skip it to avoid duplicated snapshots.
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

export const Summary: Story = {
    decorators: [width('w-[680px]')],
    render: () => renderStory(),
}

export const ChapterBesideTheChart: Story = {
    decorators: [width('w-[1100px]')],
    render: () => renderStory(),
    play: async ({ canvasElement }) => {
        // The step and the marker on the chart share this name, and either one opens the chapter.
        const [button] = await within(canvasElement).findAllByRole('button', {
            name: 'Chapter 1: A spike on October 2',
        })
        await userEvent.click(button!)
    },
}

export const EvidenceChart: Story = {
    decorators: [width('w-[1100px]')],
    render: () => renderStory(),
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const [chapter] = await canvas.findAllByRole('button', { name: 'Chapter 1: A spike on October 2' })
        await userEvent.click(chapter!)
        await userEvent.click(await canvas.findByRole('button', { name: 'Show chart' }))
    },
}

export const FunnelChapter: Story = {
    decorators: [width('w-[1100px]')],
    render: () => (
        <ExplainChartView
            data={funnelStory}
            renderChart={(overlay) => <FunnelStoryChart overlay={overlay} />}
            openLink={() => {}}
            seriesKey={FUNNEL_STEPS_BAR_SERIES_KEY}
        />
    ),
    play: async ({ canvasElement }) => {
        const [chapter] = await within(canvasElement).findAllByRole('button', {
            name: 'Chapter 2: The drop to paying',
        })
        await userEvent.click(chapter!)
    },
}

export const SingleChapter: Story = {
    decorators: [width('w-[680px]')],
    render: () => renderStory(singleChapterStory),
}
