import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonBadge, LemonButton, Tooltip } from '@posthog/lemon-ui'

import { workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { HogFlowStepNameFields } from './HogFlowStepNameFields'

export function HogFlowEditorPanelSelectedStep(): JSX.Element | null {
    const { selectedNode, selectedNodeCanBeDeleted } = useValues(hogFlowEditorLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { onNodesDelete, setSelectedNodeId } = useActions(hogFlowEditorLogic)
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
                <HogFlowStepNameFields action={action} />
            </div>
            {selectedNode.deletable && (
                <LemonButton
                    className="shrink-0"
                    size="small"
                    status="danger"
                    icon={<IconTrash />}
                    onClick={() => {
                        onNodesDelete([selectedNode])
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
