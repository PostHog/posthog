import type { Meta, StoryObj } from '@storybook/react'

import { QuillSurfaceContext } from 'lib/components/QuillSurface/quillSurfaceContext'

import __funnelTimeToConvert from '~/mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'
import __funnelTopToBottom from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'

import { InsightVizStory } from 'products/product_analytics/frontend/insights/shared/__mocks__/createInsightVizStory'

import { FunnelCanvasLabel } from './FunnelCanvasLabel'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Insights/FunnelCanvasLabel',
    component: FunnelCanvasLabel,
    parameters: { mockDate: '2023-03-01', testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const QuillSteps: Story = {
    render: () => (
        <InsightVizStory insight={__funnelTopToBottom as any}>
            <QuillSurfaceContext.Provider value={true}>
                <FunnelCanvasLabel />
            </QuillSurfaceContext.Provider>
        </InsightVizStory>
    ),
}

export const QuillTimeToConvert: Story = {
    render: () => (
        <InsightVizStory insight={__funnelTimeToConvert as any}>
            <QuillSurfaceContext.Provider value={true}>
                <FunnelCanvasLabel />
            </QuillSurfaceContext.Provider>
        </InsightVizStory>
    ),
}
