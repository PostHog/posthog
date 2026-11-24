import { Meta, StoryObj } from '@storybook/react'

import { PrototypeChartGuide } from './PrototypeChartGuide'

/** Scratch story for prototype round 19: the chart guide, for documentation only. Not committed. */
const meta: Meta<typeof PrototypeChartGuide> = {
    title: 'Prototype/v19/Chart guide',
    component: PrototypeChartGuide,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
    tags: ['test-skip'],
}
export default meta

type Story = StoryObj<typeof PrototypeChartGuide>

export const ChartGuide: Story = {}
