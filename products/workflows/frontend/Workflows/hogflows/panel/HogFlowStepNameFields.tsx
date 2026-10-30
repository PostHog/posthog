import { useActions, useValues } from 'kea'

import { EditableField } from 'lib/components/EditableField/EditableField'

import { workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { isScheduleTrigger } from '../steps/types'
import type { HogFlowAction } from '../types'

export function HogFlowStepNameFields({ action }: { action: HogFlowAction }): JSX.Element {
    const { setWorkflowAction } = useActions(hogFlowEditorLogic)
    const { isViewOnly } = useValues(workflowLogic)
    const editProps = isViewOnly ? { mode: 'view' as const, clickToEdit: false } : { clickToEdit: true }
    return (
        <>
            <EditableField
                name="step-name"
                value={action.name}
                onSave={(value) => {
                    const trimmed = value.trim()
                    if (trimmed) {
                        setWorkflowAction(action.id, { ...action, name: trimmed })
                    }
                }}
                placeholder="Step name"
                minLength={1}
                saveOnBlur
                {...editProps}
                compactButtons
                compactIcon
                className="text-sm font-semibold"
                data-attr="workflow-step-name"
            />
            {!isScheduleTrigger(action) && (!isViewOnly || !!action.description) && (
                <EditableField
                    name="step-description"
                    value={action.description || ''}
                    onSave={(value) => setWorkflowAction(action.id, { ...action, description: value.trim() })}
                    placeholder="Add a description (optional)"
                    multiline
                    saveOnBlur
                    {...editProps}
                    compactButtons
                    compactIcon
                    className="text-xs text-secondary"
                    data-attr="workflow-step-description"
                />
            )}
        </>
    )
}
