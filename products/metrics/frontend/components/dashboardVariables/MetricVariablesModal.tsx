import { BindLogic, useActions, useValues } from 'kea'

import { IconPlus, IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'

import { metricVariableEditorLogic } from './metricVariableEditorLogic'
import { MetricVariableForm } from './MetricVariableForm'
import { ownValue } from './metricVariables'

const SOURCE_LABELS: Record<MetricsDashboardVariable['source'], string> = {
    custom: 'List',
    promql: 'PromQL',
    sql: 'SQL',
    textbox: 'Text input',
}

export function MetricVariablesModal({
    dashboardId,
    variables,
    options,
    dateFrom,
    dateTo,
    addVariableOnOpen = false,
    onClose,
    onSave,
}: {
    dashboardId: number | string
    variables: MetricsDashboardVariable[]
    options: Record<string, string[]>
    dateFrom?: string | null
    dateTo?: string | null
    /** Opens on a new, empty variable instead of the first saved one. */
    addVariableOnOpen?: boolean
    onClose: () => void
    onSave: (variables: MetricsDashboardVariable[]) => void
}): JSX.Element {
    const logic = metricVariableEditorLogic({ dashboardId, variables, options, dateFrom, dateTo, addVariableOnOpen })
    const { applying, draft, selectedIndex, selectedVariable, shownErrors } = useValues(logic)
    const { addVariable, selectVariable, apply } = useActions(logic)

    return (
        <BindLogic
            logic={metricVariableEditorLogic}
            props={{ dashboardId, variables, options, dateFrom, dateTo, addVariableOnOpen }}
        >
            <LemonModal
                isOpen
                onClose={onClose}
                title="Metric variables"
                width={860}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => apply(onSave)}
                            loading={applying}
                            data-attr="dashboard-metric-variables-save"
                        >
                            Apply
                        </LemonButton>
                    </>
                }
            >
                {draft.length === 0 ? (
                    <div className="flex items-center justify-center min-h-96">
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            onClick={addVariable}
                            data-attr="dashboard-metric-variable-add"
                        >
                            Add variable
                        </LemonButton>
                    </div>
                ) : (
                    <div className="flex gap-4 min-h-96">
                        <div className="flex flex-col gap-0.5 w-48 shrink-0 border-r border-primary pr-3">
                            {draft.map((variable, index) => (
                                <LemonButton
                                    key={index}
                                    size="small"
                                    fullWidth
                                    active={index === selectedIndex}
                                    onClick={() => selectVariable(index)}
                                    sideIcon={
                                        ownValue(shownErrors, variable.name) ? (
                                            <IconWarning className="text-warning" />
                                        ) : undefined
                                    }
                                >
                                    <span className="flex flex-col items-start min-w-0">
                                        <span className="font-mono truncate max-w-full">${variable.name}</span>
                                        <span className="text-xs text-secondary font-normal">
                                            {SOURCE_LABELS[variable.source]}
                                        </span>
                                    </span>
                                </LemonButton>
                            ))}
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={<IconPlus />}
                                onClick={addVariable}
                                className="mt-1"
                                data-attr="dashboard-metric-variable-add"
                            >
                                Add variable
                            </LemonButton>
                        </div>
                        {selectedVariable && <MetricVariableForm variable={selectedVariable} />}
                    </div>
                )}
            </LemonModal>
        </BindLogic>
    )
}
