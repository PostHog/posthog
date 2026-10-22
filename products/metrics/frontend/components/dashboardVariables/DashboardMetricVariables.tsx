import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'

import { dashboardMetricVariablesLogic } from './dashboardMetricVariablesLogic'
import { ownValue, variablesToReload } from './metricVariables'
import { MetricVariableSelect } from './MetricVariableSelect'
import { MetricVariablesModal } from './MetricVariablesModal'

const NO_VARIABLES: MetricsDashboardVariable[] = []

export function DashboardMetricVariables({ editable = true }: { editable?: boolean }): JSX.Element | null {
    const { dashboard, dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setMetricVariables, setDashboardEditing } = useActions(dashboardLogic)
    const [editorOpen, setEditorOpen] = useState(false)

    const metricVariables = effectiveEditBarFilters.metricVariables
    // A name from the URL without a saved definition, such as a deleted variable, has nothing to show.
    const variables = useMemo(
        () => metricVariables?.filter((variable) => variable.source) ?? NO_VARIABLES,
        [metricVariables]
    )
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
    const { retry, select, stage } = useActions(logic)
    // Applied definitions stay staged while their options load, and the selects and the editor show them.
    const shown = pendingVariables ?? variables

    if (!dashboard) {
        return null
    }

    return (
        <div className="flex items-end gap-2 flex-wrap">
            {shown.map((variable) => (
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
            {editable && (
                <LemonButton
                    size="small"
                    type="tertiary"
                    icon={<IconGear />}
                    tooltip={shown.length ? 'Edit variables' : undefined}
                    onClick={() => setEditorOpen(true)}
                    data-attr="dashboard-metric-variables-edit"
                >
                    {shown.length ? null : 'Add variable'}
                </LemonButton>
            )}
            {editorOpen && (
                <MetricVariablesModal
                    dashboardId={dashboard.id}
                    variables={shown}
                    options={options}
                    dateFrom={effectiveEditBarFilters.date_from}
                    dateTo={effectiveEditBarFilters.date_to}
                    onClose={() => setEditorOpen(false)}
                    onSave={(next) => {
                        setEditorOpen(false)
                        stage(next, variablesToReload(shown, next))
                    }}
                />
            )}
        </div>
    )
}
