import { Meta, StoryObj } from '@storybook/react'

import { Stage, playHoverAtFraction } from '@posthog/quill-charts/story-helpers'

import { EndpointsUsageTrendsChart } from './EndpointsUsageTrendsNode'

const meta: Meta<typeof EndpointsUsageTrendsChart> = {
    title: 'Endpoints/UsageTrendsChart',
    component: EndpointsUsageTrendsChart,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof EndpointsUsageTrendsChart>

const DAYS = ['2026-07-01', '2026-07-02', '2026-07-03', '2026-07-04', '2026-07-05', '2026-07-06', '2026-07-07']

const REQUESTS_BY_ENDPOINT: Record<string, number[]> = {
    '/api/events': [210, 190, 260, 240, 300, 330, 290],
    '/api/persons': [90, 110, 80, 130, 120, 140, 100],
    '/api/insights': [40, 55, 60, 45, 70, 65, 80],
}

/**
 * One breakdown story, hovered mid-chart. Scaling and grouping are covered by
 * `endpointsUsageTrendsTransforms.test.ts`, so what a snapshot uniquely buys is that the chart
 * paints at all (it once rendered zero-height) plus the tooltip — whose date header and total row
 * no unit test reaches.
 */
export const Breakdown: Story = {
    render: () => (
        <Stage width={760}>
            <EndpointsUsageTrendsChart
                metric="requests"
                results={DAYS.flatMap((date, i) =>
                    Object.entries(REQUESTS_BY_ENDPOINT).map(([breakdown, values]) => ({
                        date,
                        breakdown,
                        value: values[i],
                    }))
                )}
            />
        </Stage>
    ),
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.5),
}
