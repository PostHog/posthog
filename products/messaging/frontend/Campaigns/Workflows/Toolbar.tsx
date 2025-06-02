import { IconDecisionTree, IconDrag, IconHourglass, IconRevert, IconSend } from '@posthog/icons'
import { Panel } from '@xyflow/react'

const TOOLBAR_NODES = [
    { type: 'email', label: 'Email', icon: <IconSend /> },
    { type: 'condition', label: 'Condition', icon: <IconDecisionTree /> },
    { type: 'delay', label: 'Wait', icon: <IconHourglass /> },
    { type: 'delay_until', label: 'Wait until', icon: <IconRevert /> },
] as const
export type ToolbarNode = (typeof TOOLBAR_NODES)[number]

// Draggable node component
function ToolbarNode({
    node,
    setNewNode,
}: {
    node: ToolbarNode
    setNewNode: (nodeType: ToolbarNode) => void
}): JSX.Element {
    const onDragStart = (event: React.DragEvent): void => {
        setNewNode(node)
        event.dataTransfer.setData('application/reactflow', node.type)
        event.dataTransfer.effectAllowed = 'move'
    }

    return (
        <div
            className="bg-surface-primary border rounded flex justify-between items-center p-2 cursor-grab hover:bg-surface-secondary"
            draggable
            onDragStart={onDragStart}
        >
            <div className="flex items-center gap-1">
                {node.icon}
                {node.label}
            </div>
            <IconDrag className="text-lg" />
        </div>
    )
}

export function Toolbar({ setNewNode }: { setNewNode: (nodeType: ToolbarNode) => void }): JSX.Element {
    return (
        <Panel position="top-left">
            <div className="bg-surface-primary rounded-md shadow-md flex flex-col gap-2 p-4 z-10 w-[200px]">
                <h3 className="font-semibold nodrag">Workflow steps</h3>
                <div className="flex flex-col gap-2">
                    {TOOLBAR_NODES.map((node) => (
                        <ToolbarNode key={node.type} node={node} setNewNode={setNewNode} />
                    ))}
                </div>
            </div>
        </Panel>
    )
}
