import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'

import { dashboardMetricVariablesLogic } from './dashboardMetricVariablesLogic'
import { ownValue } from './metricVariables'
import { MetricVariableSelect } from './MetricVariableSelect'
import { MetricVariablesModal } from './MetricVariablesModal'

const NO_VARIABLES: MetricsDashboardVariable[] = []

export function DashboardMetricVariables(): JSX.Element | null {
    const { dashboard, dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setMetricVariables, setDashboardEditing } = useActions(dashboardLogic)
    const [editorOpen, setEditorOpen] = useState(false)

    const variables = effectiveEditBarFilters.metricVariables ?? NO_VARIABLES
    const change = (next: MetricsDashboardVariable[]): void => {
        if (!dashboardEditing?.filters) {
            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
        }
        setMetricVariables(next.length ? next : null)
    }
    const logic = dashboardMetricVariablesLogic({
        dashboardId: dashboard?.id ?? 'new',
        variables,
        dateFrom: effectiveEditBarFilters.date_from,
        dateTo: effectiveEditBarFilters.date_to,
        onSelectionsChange: change,
    })
    const { options, loadingNames, errors, pendingVariables } = useValues(logic)
    const { retry, select } = useActions(logic)

    if (!dashboard) {
        return null
    }

    return (
        <div className="flex items-end gap-2 flex-wrap">
            {(pendingVariables ?? variables).map((variable) => (
                <MetricVariableSelect
                    key={variable.name}
                    variable={variable}
                    options={ownValue(options, variable.name) ?? []}
                    loading={loadingNames.includes(variable.name)}
                    error={ownValue(errors, variable.name) ?? null}
                    onRetry={() => retry(variable.name)}
                    onChange={(current) => select(variable.name, current)}
                />
            ))}
            <LemonButton
                size="small"
                type="tertiary"
                icon={<IconGear />}
                tooltip={variables.length ? 'Edit variables' : undefined}
                onClick={() => setEditorOpen(true)}
                data-attr="dashboard-metric-variables-edit"
            >
                {variables.length ? null : 'Add variable'}
            </LemonButton>
            {editorOpen && (
                <MetricVariablesModal
                    dashboardId={dashboard.id}
                    variables={variables}
                    options={options}
                    dateFrom={effectiveEditBarFilters.date_from}
                    dateTo={effectiveEditBarFilters.date_to}
                    onClose={() => setEditorOpen(false)}
                    onSave={(next) => {
                        setEditorOpen(false)
                        change(next)
                    }}
                />
            )}
        </div>
    )
}
