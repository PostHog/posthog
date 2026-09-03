import { useReactFlow } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonBadge, LemonButton, Tooltip } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'

import { workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { isScheduleTrigger } from '../steps/types'

export function HogFlowEditorPanelSelectedStep(): JSX.Element | null {
    const { selectedNode, selectedNodeCanBeDeleted } = useValues(hogFlowEditorLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { setWorkflowAction, setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { deleteElements } = useReactFlow()
    const Step = useHogFlowStep(selectedNode?.data)

    if (!selectedNode) {
        return null
    }

    const action = selectedNode.data
    const validationResult = actionValidationErrorsById[action.id]
    const hasValidationIssue =
        validationResult?.valid === false || Object.keys(validationResult?.warnings ?? {}).length > 0

    return (
        <div className="relative z-10 flex shrink-0 items-start gap-2 border-b bg-surface-primary p-2">
            <span
                className="flex size-10 shrink-0 items-center justify-center rounded text-xl"
                style={{
                    backgroundColor: Step?.color ? `${Step.color}20` : 'var(--border)',
                    color: Step?.color || 'var(--text-secondary)',
                }}
            >
                {Step?.icon}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
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
                    className="text-sm font-semibold"
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
                        className="text-xs text-secondary"
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
            {hasValidationIssue && (
                <Tooltip title="Some fields need attention">
                    <span className={`absolute top-2 ${selectedNode.deletable ? 'right-12' : 'right-2'}`}>
                        <LemonBadge status="warning" size="small" content="!" />
                    </span>
                </Tooltip>
            )}
        </div>
    )
}
