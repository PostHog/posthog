import type { Meta, StoryObj } from '@storybook/react'

import { QuillSurfaceContext } from 'lib/components/QuillSurface/quillSurfaceContext'

import __trendsBoxPlot from '~/mocks/fixtures/api/projects/team_id/insights/trendsBoxPlot.json'

import { InsightVizStory } from 'products/product_analytics/frontend/insights/shared/__mocks__/createInsightVizStory'

import { BoxPlotResultsTable } from './BoxPlotResultsTable'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Insights/BoxPlotResultsTable',
    component: BoxPlotResultsTable,
    parameters: { mockDate: '2022-03-11' },
}
export default meta

export const Quill: Story = {
    render: () => (
        <InsightVizStory insight={__trendsBoxPlot as any}>
            <QuillSurfaceContext.Provider value={true}>
                <BoxPlotResultsTable />
            </QuillSurfaceContext.Provider>
        </InsightVizStory>
    ),
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
