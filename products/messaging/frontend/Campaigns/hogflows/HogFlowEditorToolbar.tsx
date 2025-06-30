import { IconDrag } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'

import { hogFlowEditorLogic } from './hogFlowEditorLogic'
import { getHogFlowStep } from './steps/HogFlowSteps'
import { HogFlowAction } from './types'

export const TOOLBAR_NODES_TO_SHOW: HogFlowAction['type'][] = [
    'message',
    'conditional_branch',
    'delay',
    'wait_until_condition',
]

function HogFlowEditorToolbarNode({ type }: { type: HogFlowAction['type'] }): JSX.Element | null {
    const { setNewDraggingNode } = useActions(hogFlowEditorLogic)

    const onDragStart = (event: React.DragEvent): void => {
        setNewDraggingNode(type)
        event.dataTransfer.setData('application/reactflow', type)
        event.dataTransfer.effectAllowed = 'move'
    }

    const step = getHogFlowStep(type)

    if (!step) {
        return null
    }

    return (
        <div draggable onDragStart={onDragStart}>
            <LemonButton icon={step.icon} sideIcon={<IconDrag />} fullWidth>
                {step.name}
            </LemonButton>
        </div>
    )
}

export function HogFlowEditorToolbar(): JSX.Element {
    return (
        <div className="flex overflow-y-auto flex-col gap-px p-1 w-120">
            {TOOLBAR_NODES_TO_SHOW.map((type) => (
                <HogFlowEditorToolbarNode key={type} type={type} />
            ))}
        </div>
    )
}
