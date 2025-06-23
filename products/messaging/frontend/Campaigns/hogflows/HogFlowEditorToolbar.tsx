import { IconClock, IconDecisionTree, IconDrag, IconHourglass, IconSend } from '@posthog/icons'
import { Panel } from '@xyflow/react'
import { useActions } from 'kea'

import { hogFlowEditorLogic } from './hogFlowEditorLogic'

const TOOLBAR_NODES = [
    { type: 'message', name: 'Message', icon: <IconSend /> },
    { type: 'conditional_branch', name: 'Conditional', icon: <IconDecisionTree /> },
    { type: 'delay', name: 'Wait', icon: <IconClock /> },
    { type: 'wait_until_condition', name: 'Wait until...', icon: <IconHourglass /> },
] as const
export type ToolbarNode = (typeof TOOLBAR_NODES)[number]

function ToolbarNode({ node }: { node: ToolbarNode }): JSX.Element {
    const { setNewDraggingNode } = useActions(hogFlowEditorLogic)

    const onDragStart = (event: React.DragEvent): void => {
        console.log('onDragStart', node)
        setNewDraggingNode(node)
        event.dataTransfer.setData('application/reactflow', node.type)
        event.dataTransfer.effectAllowed = 'move'
    }

    return (
        <div
            className="flex justify-between items-center p-2 rounded border bg-surface-primary cursor-grab hover:bg-surface-secondary"
            draggable
            onDragStart={onDragStart}
        >
            <div className="flex gap-1 items-center">
                {node.icon}
                {node.name}
            </div>
            <IconDrag className="text-lg text-muted" />
        </div>
    )
}

export function HogFlowEditorToolbar(): JSX.Element {
    return (
        <Panel position="top-left">
            <div className="bg-surface-primary rounded-md shadow-md flex flex-col gap-2 p-4 z-10 w-[200px]">
                <h3 className="font-semibold nodrag">Workflow steps</h3>
                <div className="flex flex-col gap-2">
                    {TOOLBAR_NODES.map((node) => (
                        <ToolbarNode key={node.type} node={node} />
                    ))}
                </div>
            </div>
        </Panel>
    )
}
