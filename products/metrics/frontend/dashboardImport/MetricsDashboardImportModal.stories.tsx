import type { Meta, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import type { DashboardImportApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardImportLogic } from './metricsDashboardImportLogic'
import { MetricsDashboardImportModal } from './MetricsDashboardImportModal'

const COMPLETED_IMPORT: DashboardImportApi = {
    id: null,
    source: 'grafana',
    status: 'completed',
    dashboard_name: 'Checkout service',
    progress: null,
    dashboard_id: 1,
    error: null,
    summary: { total: 6, imported: 3, approximated: 1, failed: 1, skipped: 1 },
    panels: [
        { key: 'p1', title: 'Request rate', outcome: 'imported', reason: '' },
        { key: 'p2', title: 'Error ratio', outcome: 'imported', reason: '' },
        {
            key: 'p3',
            title: 'Latency p95',
            outcome: 'approximated',
            reason: 'Uses http.server.request.duration in place of http_request_duration_seconds.',
        },
        { key: 'p4', title: 'Pod restarts', outcome: 'failed', reason: 'This project has no metric for pod restarts.' },
        { key: 'p5', title: 'Error logs', outcome: 'imported', reason: '' },
        { key: 'p6', title: 'Service map', outcome: 'skipped', reason: 'PostHog has no node graph panel.' },
    ],
}

const meta: Meta<typeof MetricsDashboardImportModal> = {
    title: 'Metrics/MetricsDashboardImportModal',
    component: MetricsDashboardImportModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-01',
    },
}

export default meta

type Story = StoryObj<typeof MetricsDashboardImportModal>

export const ImportSummary: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            metricsDashboardImportLogic.actions.openImportModal('grafana')
            metricsDashboardImportLogic.actions.startImportSuccess(COMPLETED_IMPORT, null)
        })

        return <MetricsDashboardImportModal />
    },
}
