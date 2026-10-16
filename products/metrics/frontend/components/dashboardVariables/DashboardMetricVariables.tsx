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

/** The dashboard's metric variables: one select per variable, and a button that opens the variable editor. */
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
    const { options, loadingNames, errors } = useValues(logic)
    const { retry } = useActions(logic)

    if (!dashboard) {
        return null
    }

    return (
        <div className="flex items-end gap-2 flex-wrap">
            {variables.map((variable) => (
                <MetricVariableSelect
                    key={variable.name}
                    variable={variable}
                    options={ownValue(options, variable.name) ?? []}
                    loading={loadingNames.includes(variable.name)}
                    error={ownValue(errors, variable.name) ?? null}
                    onRetry={() => retry(variable.name)}
                    onChange={(current) =>
                        change(variables.map((other) => (other.name === variable.name ? { ...other, current } : other)))
                    }
                />
            ))}
            <LemonButton
                size="small"
                type="tertiary"
                icon={<IconGear />}
                tooltip={variables.length ? 'Edit variables' : 'Add a variable that metrics tiles refer to as $name'}
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
