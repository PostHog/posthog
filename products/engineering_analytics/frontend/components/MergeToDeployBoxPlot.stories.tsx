import type { Meta, StoryObj } from '@storybook/react'

import { MergeToDeployBoxPlot, type BoxPlotBucket } from './MergeToDeployBoxPlot'

function bucket(
    label: string,
    count: number,
    seconds: [number, number, number, number, number, number]
): BoxPlotBucket {
    const [min, p25, p50, mean, p75, max] = seconds
    return {
        label,
        count,
        minSeconds: min,
        p25Seconds: p25,
        p50Seconds: p50,
        meanSeconds: mean,
        p75Seconds: p75,
        maxSeconds: max,
    }
}

const EMPTY_BUCKET: BoxPlotBucket = {
    label: 'Jul 13',
    count: 0,
    minSeconds: null,
    p25Seconds: null,
    p50Seconds: null,
    meanSeconds: null,
    p75Seconds: null,
    maxSeconds: null,
}

const BUCKETS: BoxPlotBucket[] = [
    bucket('Jul 7', 14, [600, 1800, 3600, 4600, 7200, 14400]),
    bucket('Jul 8', 22, [900, 2400, 4200, 5200, 6000, 21600]),
    bucket('Jul 9', 9, [1200, 3000, 5400, 6800, 9600, 18000]),
    bucket('Jul 10', 17, [600, 1500, 2700, 3400, 4800, 9000]),
    bucket('Jul 11', 5, [1800, 3600, 7200, 11500, 14400, 43200]),
    bucket('Jul 12', 1, [5400, 5400, 5400, 5400, 5400, 5400]),
    { ...EMPTY_BUCKET },
    bucket('Jul 14', 11, [600, 1200, 2400, 2900, 3600, 7200]),
]

const meta: Meta<typeof MergeToDeployBoxPlot> = {
    title: 'Scenes-App/Engineering Analytics/Merge To Deploy Box Plot',
    component: MergeToDeployBoxPlot,
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '[data-attr="merge-to-deploy-box-plot-story"] canvas',
            viewport: { width: 1280, height: 400 },
        },
    },
    decorators: [
        (Story) => (
            <div className="p-6" data-attr="merge-to-deploy-box-plot-story">
                <Story />
            </div>
        ),
    ],
    args: {
        buckets: BUCKETS,
        formatSeconds: (seconds: number) => `${Math.round(seconds / 60)}m`,
    },
}

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}
