import type { Meta, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { metricsPrometheusConnectLogic } from './metricsPrometheusConnectLogic'
import { MetricsPrometheusConnectModal } from './MetricsPrometheusConnectModal'

const meta: Meta<typeof MetricsPrometheusConnectModal> = {
    title: 'Metrics/MetricsPrometheusConnectModal',
    component: MetricsPrometheusConnectModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-01',
        testOptions: { snapshotBrowsers: [] },
    },
}

export default meta

type Story = StoryObj<typeof MetricsPrometheusConnectModal>

export const FailedConnectionTest: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            metricsPrometheusConnectLogic.actions.openConnectModal()
            metricsPrometheusConnectLogic.actions.testConnectionSuccess({
                status: 'error',
                message: 'PromQL/LogQL query API is not configured',
            })
        })

        return <MetricsPrometheusConnectModal />
    },
}
