import { Meta, StoryObj } from '@storybook/react'

import __trendsBoxPlot from '~/mocks/fixtures/api/projects/team_id/insights/trendsBoxPlot.json'

import { InsightVizStory } from 'products/product_analytics/frontend/insights/shared/__mocks__/createInsightVizStory'

import { BoxPlotChart } from './BoxPlotChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/BoxPlot',
    component: BoxPlotChart,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-11',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '[data-attr=box-plot-graph] > canvas',
        },
    },
}
export default meta

export const Default: Story = {
    render: () => <InsightVizStory insight={__trendsBoxPlot as any} />,
}
