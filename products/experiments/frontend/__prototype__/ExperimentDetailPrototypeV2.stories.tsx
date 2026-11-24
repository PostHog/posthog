import { Meta, StoryObj } from '@storybook/react'

import { PROTOTYPE_STATUS } from './prototypeData'
import { PrototypeExperimentPageV2, TREND_LAYOUT } from './PrototypeExperimentPageV2'

/** Scratch stories for the experiment detail prototype, round 2. Not committed. */
const meta: Meta<typeof PrototypeExperimentPageV2> = {
    title: 'Prototype/Experiment detail v2',
    component: PrototypeExperimentPageV2,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof PrototypeExperimentPageV2>

export const RunningPerMetricChart: Story = {
    args: { status: PROTOTYPE_STATUS.running, trendLayout: TREND_LAYOUT.perMetric },
}

export const RunningPerMetricChartScrolled: Story = {
    args: { status: PROTOTYPE_STATUS.running, trendLayout: TREND_LAYOUT.perMetric },
    play: async ({ canvasElement }) => {
        canvasElement.querySelector<HTMLElement>('[data-attr="prototype-scroll"]')?.scrollTo({ top: 420 })
    },
}

export const RunningPerRowSparkline: Story = {
    args: { status: PROTOTYPE_STATUS.running, trendLayout: TREND_LAYOUT.perRow },
}

export const CompletePerMetricChart: Story = {
    args: { status: PROTOTYPE_STATUS.complete, trendLayout: TREND_LAYOUT.perMetric },
}
