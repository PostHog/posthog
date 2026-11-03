import type { Meta, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import type { MetricsSuggestedDashboardApi } from 'products/metrics/frontend/generated/api.schemas'

import { suggestedDashboardsLogic } from './suggestedDashboardsLogic'
import { SuggestedDashboardsMenu } from './SuggestedDashboardsMenu'

const SUGGESTIONS: MetricsSuggestedDashboardApi[] = [
    {
        id: '0b5e7c3a-2f1d-4c8e-9a6b-3d2f1e0c9b8a',
        template_id: '1c6f8d4b-3a2e-4d9f-8b7c-4e3a2f1d0c9b',
        name: 'Envoy proxy',
        description: 'Upstream traffic, errors, latency and connections of Envoy clusters.',
        reason: 'Cluster traffic, errors and latency',
        panel_count: 11,
        matched_metric_count: 10,
        coverage: 1,
        dashboard_id: null,
    },
    {
        id: '2d7a9e5c-4b3f-4e0a-9c8d-5f4b3a2e1d0c',
        template_id: '3e8b0f6d-5c4a-4f1b-8d9e-6a5c4b3f2e1d',
        name: 'Checkout',
        description: 'Orders, payments, fraud checks and webhooks of the checkout flow.',
        reason: 'Orders, payments and fraud checks',
        panel_count: 12,
        matched_metric_count: 8,
        coverage: 1,
        dashboard_id: 12,
    },
]

const meta: Meta<typeof SuggestedDashboardsMenu> = {
    title: 'Metrics/SuggestedDashboardsMenu',
    component: SuggestedDashboardsMenu,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2026-10-01',
    },
}

export default meta

type Story = StoryObj<typeof SuggestedDashboardsMenu>

export const Open: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            suggestedDashboardsLogic.actions.loadSuggestionsSuccess(SUGGESTIONS)
        })
        return (
            <div className="h-80">
                <SuggestedDashboardsMenu />
            </div>
        )
    },
    play: async ({ canvas, userEvent }): Promise<void> => {
        await userEvent.click(await canvas.findByText('Suggested'))
    },
}
