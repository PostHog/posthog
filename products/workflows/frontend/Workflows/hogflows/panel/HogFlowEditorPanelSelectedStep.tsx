import { useReactFlow } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { isScheduleTrigger } from '../steps/types'

export function HogFlowEditorPanelSelectedStep(): JSX.Element | null {
    const { selectedNode, selectedNodeCanBeDeleted } = useValues(hogFlowEditorLogic)
    const { setWorkflowAction, setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { deleteElements } = useReactFlow()
    const Step = useHogFlowStep(selectedNode?.data)

    if (!selectedNode) {
        return null
    }

    const action = selectedNode.data

    return (
        <div className="flex shrink-0 items-start gap-3 border-b p-3">
            <span
                className="flex size-12 shrink-0 items-center justify-center rounded text-2xl"
                style={{
                    backgroundColor: Step?.color ? `${Step.color}20` : 'var(--border)',
                    color: Step?.color || 'var(--text-secondary)',
                }}
            >
                {Step?.icon}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
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
                    clickToEdit
                    compactButtons
                    compactIcon
                    className="font-semibold text-base"
                    data-attr="workflow-step-name"
                />
                {!isScheduleTrigger(action) && (
                    <EditableField
                        name="step-description"
                        value={action.description || ''}
                        onSave={(value) => setWorkflowAction(action.id, { ...action, description: value.trim() })}
                        placeholder="Add a description (optional)"
                        multiline
                        saveOnBlur
                        clickToEdit
                        compactButtons
                        compactIcon
                        className="text-sm text-secondary"
                        data-attr="workflow-step-description"
                    />
                )}
            </div>
            {selectedNode.deletable && (
                <LemonButton
                    className="shrink-0"
                    size="small"
                    status="danger"
                    icon={<IconTrash />}
                    onClick={() => {
                        void deleteElements({ nodes: [selectedNode] })
                        setSelectedNodeId(null)
                    }}
                    disabledReason={selectedNodeCanBeDeleted ? undefined : 'Clean up branching steps first'}
                />
            )}
        </div>
    )
}
