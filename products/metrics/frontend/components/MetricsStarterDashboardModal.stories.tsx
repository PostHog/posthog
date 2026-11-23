import type { Meta, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { metricsStarterDashboardLogic } from './metricsStarterDashboardLogic'
import { MetricsStarterDashboardModal } from './MetricsStarterDashboardModal'

const meta: Meta<typeof MetricsStarterDashboardModal> = {
    title: 'Metrics/MetricsStarterDashboardModal',
    component: MetricsStarterDashboardModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-01',
        // The checkbox renders only after the derived-names lookup resolves.
        testOptions: { waitForSelector: '[data-attr="metrics-starter-dashboard-service-panels"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/metrics/names/': {
                    results: [
                        { name: 'checkout.orders.placed', metric_type: 'sum' },
                        { name: 'checkout.queue.depth', metric_type: 'gauge' },
                        { name: 'posthog.derived.spans.requests', metric_type: 'sum' },
                        { name: 'posthog.derived.spans.errors', metric_type: 'sum' },
                        { name: 'posthog.derived.spans.duration', metric_type: 'histogram' },
                    ],
                },
                '/api/projects/:team_id/metrics/attribute_values/': {
                    results: [
                        { id: 'checkout', name: 'checkout', count: 10 },
                        { id: 'billing-worker', name: 'billing-worker', count: 5 },
                    ],
                },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<typeof MetricsStarterDashboardModal>

// A team that sends traces is offered request rate, error rate and latency per service.
export const WithServiceHealthPanels: Story = {
    // The panels need tracing access, which Storybook's default app context doesn't grant.
    beforeEach: () => {
        const appContext = window.POSTHOG_APP_CONTEXT
        if (!appContext) {
            return
        }
        const originalAccess = appContext.resource_access_control
        appContext.resource_access_control = {
            ...originalAccess,
            [AccessControlResourceType.Tracing]: AccessControlLevel.Viewer,
        }
        return () => {
            appContext.resource_access_control = originalAccess
        }
    },
    render: () => {
        useDelayedOnMountEffect(() => {
            metricsStarterDashboardLogic.actions.openModal()
            metricsStarterDashboardLogic.actions.setDashboardName('Checkout')
        })

        return <MetricsStarterDashboardModal />
    },
}
