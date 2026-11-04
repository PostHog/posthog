import { Meta, StoryObj } from '@storybook/react'

import __trendsRegionMap from '~/mocks/fixtures/api/projects/team_id/insights/trendsRegionMap.json'

import { InsightVizStory } from 'products/product_analytics/frontend/insights/shared/__mocks__/createInsightVizStory'

import { RegionMap } from './RegionMap'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/RegionMap',
    component: RegionMap,
    parameters: {
        layout: 'centered',
        mockDate: '2022-04-05',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '.RegionMap',
        },
    },
}
export default meta

export const Default: Story = {
    render: () => <InsightVizStory insight={__trendsRegionMap as any} />,
}
