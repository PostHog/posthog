import { Meta, StoryObj } from '@storybook/react'

import { getDefaultQuery } from '~/queries/nodes/InsightViz/utils'
import { InsightType } from '~/types'

import { InsightHomeGuide } from './InsightHomeGuide'

const meta: Meta<typeof InsightHomeGuide> = {
    component: InsightHomeGuide,
    title: 'Scenes-App/Insights/Product analytics/Insight home guide',
    parameters: {
        pageUrl: '/insights/new?homeGuide=FUNNELS#insight=FUNNELS',
        layout: 'centered',
    },
    render: (args) => (
        <div className="w-[960px] max-w-full">
            <InsightHomeGuide {...args} />
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof InsightHomeGuide>

export const Funnels: Story = {
    args: { query: getDefaultQuery(InsightType.FUNNELS, false) },
}

export const Paths: Story = {
    parameters: { pageUrl: '/insights/new?homeGuide=PATHS#insight=PATHS' },
    args: { query: getDefaultQuery(InsightType.PATHS, false) },
}

export const Stickiness: Story = {
    parameters: { pageUrl: '/insights/new?homeGuide=STICKINESS#insight=STICKINESS' },
    args: { query: getDefaultQuery(InsightType.STICKINESS, false) },
}

export const Narrow: Story = {
    args: { query: getDefaultQuery(InsightType.FUNNELS, false) },
    render: (args) => (
        <div className="w-[512px] max-w-full">
            <InsightHomeGuide {...args} />
        </div>
    ),
}

export const Phone: Story = {
    args: { query: getDefaultQuery(InsightType.FUNNELS, false) },
    render: (args) => (
        <div className="w-72">
            <InsightHomeGuide {...args} />
        </div>
    ),
}
