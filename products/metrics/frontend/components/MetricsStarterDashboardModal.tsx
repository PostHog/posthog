import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { MetricsStarterDashboardForm } from './MetricsStarterDashboardForm'
import { metricsStarterDashboardLogic } from './metricsStarterDashboardLogic'

export function MetricsStarterDashboardModal(): JSX.Element {
    const { isModalOpen, creating } = useValues(metricsStarterDashboardLogic)
    const { closeModal } = useActions(metricsStarterDashboardLogic)

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            closable={!creating}
            title="New service dashboard"
            description="Choose metrics for a service. Add other panels to the dashboard afterward."
        >
            <MetricsStarterDashboardForm onCancel={closeModal} />
        </LemonModal>
    )
}
