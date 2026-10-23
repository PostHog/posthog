import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'

import { dashboardMetricVariablesLogic } from './dashboardMetricVariablesLogic'
import { ownValue, variablesToReload } from './metricVariables'
import { MetricVariableSelect } from './MetricVariableSelect'
import { MetricVariablesModal } from './MetricVariablesModal'

const NO_VARIABLES: MetricsDashboardVariable[] = []

type EditorMode = 'edit' | 'add'

export function DashboardMetricVariables({ editable = true }: { editable?: boolean }): JSX.Element | null {
    const { dashboard, dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setMetricVariables, setDashboardEditing } = useActions(dashboardLogic)
    const [editorMode, setEditorMode] = useState<EditorMode | null>(null)

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
            {editable && shown.length > 0 && (
                <LemonButton
                    size="small"
                    type="tertiary"
                    icon={<IconGear />}
                    tooltip="Edit variables"
                    onClick={() => setEditorMode('edit')}
                    data-attr="dashboard-metric-variables-edit"
                />
            )}
            {editable && (
                <LemonButton
                    size="small"
                    type="tertiary"
                    icon={<IconPlusSmall />}
                    onClick={() => setEditorMode('add')}
                    data-attr="dashboard-metric-variables-add"
                >
                    Add variable
                </LemonButton>
            )}
            {editorMode && (
                <MetricVariablesModal
                    dashboardId={dashboard.id}
                    variables={shown}
                    options={options}
                    dateFrom={effectiveEditBarFilters.date_from}
                    dateTo={effectiveEditBarFilters.date_to}
                    addVariableOnOpen={editorMode === 'add'}
                    onClose={() => setEditorMode(null)}
                    onSave={(next) => {
                        setEditorMode(null)
                        stage(next, variablesToReload(shown, next))
                    }}
                />
            )}
        </div>
    )
}
