import type { Meta, StoryObj } from '@storybook/react'

import { QuillSurfaceContext } from 'lib/components/QuillSurface/quillSurfaceContext'

import __funnelTopToBottomBreakdown from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'

import { InsightVizStory } from 'products/product_analytics/frontend/insights/shared/__mocks__/createInsightVizStory'

import { FunnelStepsTable } from './FunnelStepsTable'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Insights/FunnelStepsTable',
    component: FunnelStepsTable,
    parameters: { mockDate: '2023-03-01' },
}
export default meta

export const Quill: Story = {
    render: () => (
        <InsightVizStory insight={__funnelTopToBottomBreakdown as any}>
            <QuillSurfaceContext.Provider value={true}>
                <FunnelStepsTable />
            </QuillSurfaceContext.Provider>
        </InsightVizStory>
    ),
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
