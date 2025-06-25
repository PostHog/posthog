import { IconDrag } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { Panel } from '@xyflow/react'
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
        <Panel position="top-left" className="bottom">
            <div className="z-10 rounded-md border shadow-lg bg-surface-primary">
                <h3 className="px-3 my-2 font-semibold">Workflow steps</h3>
                <LemonDivider className="my-0" />
                <div className="flex overflow-y-auto flex-col gap-px p-1">
                    {TOOLBAR_NODES_TO_SHOW.map((type) => (
                        <HogFlowEditorToolbarNode key={type} type={type} />
                    ))}
                </div>
            </div>
        </Panel>
    )
}
