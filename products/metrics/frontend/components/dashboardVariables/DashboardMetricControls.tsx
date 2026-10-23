import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconGear, IconPlusSmall, IconWarning } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardControlScopeText, isDashboardControlHidden } from 'scenes/dashboard/dashboardControls'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'

import { DashboardMetricLabelFilter } from '../DashboardMetricLabelFilter'
import { dashboardMetricVariablesLogic } from './dashboardMetricVariablesLogic'
import { ownValue, variablesToReload } from './metricVariables'
import { MetricVariableSelect } from './MetricVariableSelect'
import { MetricVariablesModal } from './MetricVariablesModal'

const NO_VARIABLES: MetricsDashboardVariable[] = []
const UNUSED_FILTERS_REASON =
    'No insight on this dashboard uses label filters. Only metrics insights made in the query builder use them.'

type EditorMode = 'edit' | 'add'

/** The metrics group of the dashboard filter bar: variable selects and label filters, with "Add variable" and "Add filter". */
export function DashboardMetricControls({
    editable = true,
    className,
}: {
    editable?: boolean
    className?: string
}): JSX.Element | null {
    const { dashboard, dashboardEditing, effectiveEditBarFilters, dashboardControlScopes } = useValues(dashboardLogic)
    const { setMetricVariables, setMetricFilters, setDashboardEditing } = useActions(dashboardLogic)
    const [editorMode, setEditorMode] = useState<EditorMode | null>(null)

    const metricVariables = effectiveEditBarFilters.metricVariables
    // A name from the URL without a saved definition, such as a deleted variable, has nothing to show.
    const variables = useMemo(
        () => metricVariables?.filter((variable) => variable.source) ?? NO_VARIABLES,
        [metricVariables]
    )
    const startEditing = (): void => {
        if (!dashboardEditing?.filters) {
            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
        }
    }
    const change = (next: MetricsDashboardVariable[]): void => {
        startEditing()
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

    const labelsScope = dashboardControlScopes.metricLabels
    const hasFilters = (effectiveEditBarFilters.metricFilters?.length ?? 0) > 0
    // Label filters reach builder tiles only, so a dashboard of PromQL or SQL tiles offers variables without filters.
    const showFilters = editable && !isDashboardControlHidden(labelsScope, hasFilters)
    // A saved filter stays visible when no tile uses it, so that the user can remove it.
    const filtersUnused = showFilters && labelsScope.total > 0 && labelsScope.applies === 0
    const showVariables =
        shown.length > 0 ||
        (editable && !isDashboardControlHidden(dashboardControlScopes.metricVariables, shown.length > 0))
    if (!showFilters && !showVariables) {
        return null
    }

    const addVariableButton = editable && showVariables && (
        <LemonButton
            size="small"
            type="tertiary"
            icon={<IconPlusSmall />}
            tooltip={dashboardControlScopeText(dashboardControlScopes.metricVariables)}
            onClick={() => setEditorMode('add')}
            data-attr="dashboard-metric-variables-add"
        >
            Add variable
        </LemonButton>
    )

    return (
        <div className={clsx('flex items-end gap-2 flex-wrap', className)}>
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
            {showFilters ? (
                <div className="flex min-h-[30px] items-center">
                    <DashboardMetricLabelFilter
                        metricFilters={effectiveEditBarFilters.metricFilters}
                        onChange={(metricFilters) => {
                            startEditing()
                            setMetricFilters(metricFilters)
                        }}
                        addFilterTooltip={dashboardControlScopeText(labelsScope)}
                        addFilterDisabledReason={filtersUnused ? UNUSED_FILTERS_REASON : null}
                        actionsBeforeAddFilter={addVariableButton}
                    />
                    {filtersUnused && (
                        <Tooltip title={UNUSED_FILTERS_REASON}>
                            <span tabIndex={0} role="img" aria-label={UNUSED_FILTERS_REASON} className="flex">
                                <IconWarning className="text-warning text-lg" />
                            </span>
                        </Tooltip>
                    )}
                </div>
            ) : (
                addVariableButton
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
