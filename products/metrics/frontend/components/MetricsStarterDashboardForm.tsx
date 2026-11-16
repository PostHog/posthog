import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { metricOptionKey, metricsStarterDashboardLogic } from './metricsStarterDashboardLogic'

export function MetricsStarterDashboardForm({
    onCancel,
    onCreated,
}: {
    onCancel: () => void
    onCreated?: () => void
}): JSX.Element {
    const {
        dashboardName,
        serviceName,
        selectedMetrics,
        services,
        servicesLoading,
        metricOptions,
        metricOptionsLoading,
        creating,
    } = useValues(metricsStarterDashboardLogic)
    const { setDashboardName, setServiceName, setSelectedMetrics, createDashboard } =
        useActions(metricsStarterDashboardLogic)

    return (
        <div className="flex flex-col gap-3">
            <LemonInput
                value={dashboardName}
                onChange={setDashboardName}
                placeholder="Dashboard name, e.g. Billing worker"
                aria-label="Dashboard name"
                autoFocus
                disabled={creating}
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
                disabledReason={creating ? 'Creating…' : undefined}
                data-attr="metrics-starter-dashboard-service"
            />
            <LemonInputSelect
                mode="multiple"
                value={selectedMetrics}
                onChange={setSelectedMetrics}
                loading={metricOptionsLoading}
                options={metricOptions.map((option) => ({
                    key: metricOptionKey(option.name, option.metric_type),
                    label: option.name,
                }))}
                placeholder="Pick the metrics to chart"
                disabled={creating}
                data-attr="metrics-starter-dashboard-metrics"
            />
            <div className="flex justify-end gap-2 border-t pt-4 mt-2">
                <LemonButton type="secondary" onClick={onCancel} disabledReason={creating ? 'Creating…' : undefined}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={() => createDashboard(onCreated)}
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
            </div>
        </div>
    )
}
