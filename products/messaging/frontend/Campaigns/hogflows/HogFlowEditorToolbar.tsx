import { IconDrag } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions } from 'kea'

import { hogFlowEditorLogic } from './hogFlowEditorLogic'
import { getHogFlowStep } from './steps/HogFlowSteps'
import { HogFlowAction } from './types'

export const ACTION_NODES_TO_SHOW: HogFlowAction['type'][] = [
    'function_email',
    'function_sms',
    'function_slack',
    'function_webhook',
]

export const DELAY_NODES_TO_SHOW: HogFlowAction['type'][] = ['delay', 'wait_until_time_window', 'wait_until_condition']

export const LOGIC_NODES_TO_SHOW: HogFlowAction['type'][] = ['conditional_branch', 'random_cohort_branch']

function HogFlowEditorToolbarNode({ type }: { type: HogFlowAction['type'] }): JSX.Element | null {
    const { setNewDraggingNode } = useActions(hogFlowEditorLogic)

    const onDragStart = (event: React.DragEvent): void => {
        setNewDraggingNode(type)
        event.dataTransfer.setData('application/reactflow', type)
        event.dataTransfer.effectAllowed = 'move'
    }

    const onDrop = (event: React.DragEvent): void => {
        // Check if the drop is within the bounds of HogFlowEditorToolbar
        const toolbar = document.querySelector('.hog-flow-editor-toolbar')
        if (toolbar) {
            const rect = toolbar.getBoundingClientRect()
            const { clientX, clientY } = event

            if (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom) {
                // Stop propagation if dropped within toolbar bounds
                event.preventDefault()
                event.stopPropagation()
            }
        }
    }

    const step = getHogFlowStep(type)

    if (!step) {
        return null
    }

    return (
        <div draggable onDragStart={onDragStart} onDrop={onDrop}>
            <LemonButton icon={step.icon} sideIcon={<IconDrag />} fullWidth>
                {step.name}
            </LemonButton>
        </div>
    )
}

export function HogFlowEditorToolbar(): JSX.Element {
    return (
        <div className="hog-flow-editor-toolbar flex overflow-y-auto flex-col gap-px p-2 max-h-120">
            <span className="flex gap-2 text-sm font-semibold mt-2 items-center">
                Actions <LemonDivider className="flex-1" />
            </span>
            {ACTION_NODES_TO_SHOW.map((type) => (
                <HogFlowEditorToolbarNode key={type} type={type} />
            ))}

            <span className="flex gap-2 text-sm font-semibold mt-2 items-center">
                Delays <LemonDivider className="flex-1" />
            </span>
            {DELAY_NODES_TO_SHOW.map((type) => (
                <HogFlowEditorToolbarNode key={type} type={type} />
            ))}

            <span className="flex gap-2 text-sm font-semibold mt-2 items-center">
                Audience split <LemonDivider className="flex-1" />
            </span>
            {LOGIC_NODES_TO_SHOW.map((type) => (
                <HogFlowEditorToolbarNode key={type} type={type} />
            ))}
        </div>
    )
}
