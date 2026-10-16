import { BindLogic, useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'

import { metricVariableEditorLogic } from './metricVariableEditorLogic'
import { MetricVariableForm } from './MetricVariableForm'

/** Adds, changes, orders and removes the metric variables of a dashboard. */
export function MetricVariablesModal({
    dashboardId,
    variables,
    onClose,
    onSave,
}: {
    dashboardId: number | string
    variables: MetricsDashboardVariable[]
    onClose: () => void
    onSave: (variables: MetricsDashboardVariable[]) => void
}): JSX.Element {
    const logic = metricVariableEditorLogic({ dashboardId, variables })
    const { draft, selectedIndex, selectedVariable, errors } = useValues(logic)
    const { addVariable, removeVariable, moveVariable, selectVariable } = useActions(logic)
    const hasErrors = Object.keys(errors).length > 0

    return (
        <BindLogic logic={metricVariableEditorLogic} props={{ dashboardId, variables }}>
            <LemonModal
                isOpen
                onClose={onClose}
                title="Metric variables"
                description="Metrics tiles refer to a variable as $name in PromQL, SQL and filter values."
                width={800}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={hasErrors ? 'Fix the variable settings first' : undefined}
                            onClick={() => onSave(draft)}
                            data-attr="dashboard-metric-variables-save"
                        >
                            Apply
                        </LemonButton>
                    </>
                }
            >
                <div className="flex gap-4 min-h-80 @container">
                    <div className="flex flex-col gap-1 w-48 shrink-0">
                        {draft.map((variable, index) => (
                            <LemonButton
                                key={index}
                                size="small"
                                fullWidth
                                active={index === selectedIndex}
                                status={errors[variable.name] ? 'danger' : 'default'}
                                onClick={() => selectVariable(index)}
                                sideAction={{
                                    icon: <IconTrash />,
                                    tooltip: 'Remove',
                                    onClick: () => removeVariable(index),
                                }}
                            >
                                ${variable.name}
                            </LemonButton>
                        ))}
                        <LemonButton
                            size="small"
                            icon={<IconPlus />}
                            onClick={addVariable}
                            data-attr="dashboard-metric-variable-add"
                        >
                            Add variable
                        </LemonButton>
                        {selectedVariable && draft.length > 1 && (
                            <div className="flex gap-1">
                                <LemonButton
                                    size="small"
                                    icon={<IconArrowUp />}
                                    tooltip="Move up"
                                    disabledReason={selectedIndex === 0 ? 'This is the first variable' : undefined}
                                    onClick={() => moveVariable(selectedIndex, -1)}
                                />
                                <LemonButton
                                    size="small"
                                    icon={<IconArrowDown />}
                                    tooltip="Move down"
                                    disabledReason={
                                        selectedIndex === draft.length - 1 ? 'This is the last variable' : undefined
                                    }
                                    onClick={() => moveVariable(selectedIndex, 1)}
                                />
                            </div>
                        )}
                    </div>
                    {selectedVariable ? (
                        <MetricVariableForm variable={selectedVariable} />
                    ) : (
                        <p className="text-secondary flex-1">
                            Add a variable. Then refer to it as $name in the PromQL, SQL or filters of a metrics tile.
                        </p>
                    )}
                </div>
            </LemonModal>
        </BindLogic>
    )
}
