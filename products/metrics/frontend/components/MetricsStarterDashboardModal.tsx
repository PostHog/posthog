import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonInputSelect, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { metricOptionKey, metricsStarterDashboardLogic } from './metricsStarterDashboardLogic'

export function MetricsStarterDashboardModal(): JSX.Element {
    const {
        isModalOpen,
        dashboardName,
        serviceName,
        selectedMetrics,
        services,
        servicesLoading,
        metricOptions,
        metricOptionsLoading,
        creating,
    } = useValues(metricsStarterDashboardLogic)
    const { closeModal, setDashboardName, setServiceName, setSelectedMetrics, createDashboard } =
        useActions(metricsStarterDashboardLogic)

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            closable={!creating}
            title="New service dashboard"
            description="One insight per metric, charted with its recommended aggregation."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={creating ? 'Creating…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={createDashboard}
                        loading={creating}
                        disabledReason={
                            !dashboardName.trim()
                                ? 'Name the dashboard'
                                : !selectedMetrics.length
                                  ? 'Pick at least one metric'
                                  : undefined
                        }
                        data-attr="metrics-starter-dashboard-create"
                    >
                        Create dashboard
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <LemonInput
                    value={dashboardName}
                    onChange={setDashboardName}
                    placeholder="Dashboard name, e.g. Billing worker"
                    autoFocus
                    data-attr="metrics-starter-dashboard-name"
                />
                <LemonSelect
                    value={serviceName}
                    onChange={(value) => setServiceName(value ?? '')}
                    loading={servicesLoading}
                    options={[
                        { value: '', label: 'All services' },
                        ...services.map((service) => ({ value: service, label: service })),
                    ]}
                    placeholder="Scope to a service"
                    fullWidth
                    data-attr="metrics-starter-dashboard-service"
                />
                <LemonInputSelect
                    mode="multiple"
                    value={selectedMetrics}
                    onChange={setSelectedMetrics}
                    loading={metricOptionsLoading}
                    options={metricOptions.map((option) => ({
                        // Composite key: the same name can exist under two OTel types.
                        key: metricOptionKey(option.name, option.metric_type),
                        label: `${option.name} (${option.metric_type})`,
                    }))}
                    placeholder="Pick the metrics to chart"
                    data-attr="metrics-starter-dashboard-metrics"
                />
            </div>
        </LemonModal>
    )
}
