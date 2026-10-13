import { useActions, useValues } from 'kea'

import { IconTrash, IconTrends, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, Tooltip } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { urls } from 'scenes/urls'

import { EXIT_NODE_ID, TRIGGER_NODE_ID, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { isScheduleTrigger } from '../steps/types'

export function HogFlowEditorPanelSelectedStep(): JSX.Element | null {
    const { selectedNode, selectedNodeCanBeDeleted, workflow } = useValues(hogFlowEditorLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { onNodesDelete, setWorkflowAction, setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const Step = useHogFlowStep(selectedNode?.data)

    if (!selectedNode) {
        return null
    }

    const action = selectedNode.data
    const validationResult = actionValidationErrorsById[action.id]
    const hasValidationIssue =
        validationResult?.valid === false || Object.keys(validationResult?.warnings ?? {}).length > 0
    // The metrics tab can drill into a single step, but trigger and exit only exist in its workflow totals.
    const showStepMetricsLink =
        !!workflow.id &&
        workflow.id !== 'new' &&
        workflow.trigger?.type !== 'batch' &&
        ![TRIGGER_NODE_ID, EXIT_NODE_ID].includes(action.id)

    return (
        <div className="flex shrink-0 items-start gap-2 border-b bg-surface-primary p-2">
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
            <div className="flex shrink-0 items-center gap-1">
                {hasValidationIssue && (
                    <Tooltip title="Some fields need attention">
                        <span className="flex px-1">
                            <LemonBadge status="warning" size="small" content="!" />
                        </span>
                    </Tooltip>
                )}
                {showStepMetricsLink && (
                    <LemonButton
                        size="small"
                        icon={<IconTrends />}
                        to={`${urls.workflow(workflow.id, 'metrics')}?action=${encodeURIComponent(action.id)}`}
                        tooltip="View metrics for this step"
                        data-attr="workflow-step-metrics-link"
                    />
                )}
                {selectedNode.deletable && (
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={() => {
                            onNodesDelete([selectedNode])
                            setSelectedNodeId(null)
                        }}
                        tooltip="Delete step"
                        disabledReason={selectedNodeCanBeDeleted ? undefined : 'Clean up branching steps first'}
                    />
                )}
                <LemonButton
                    aria-label="Close step"
                    size="small"
                    icon={<IconX />}
                    onClick={() => setSelectedNodeId(null)}
                    data-attr="workflow-step-close"
                />
            </div>
        </div>
    )
}
