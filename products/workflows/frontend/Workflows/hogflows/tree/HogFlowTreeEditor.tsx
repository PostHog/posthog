import { useValues } from 'kea'
import { useMemo, useState } from 'react'
import type { DragEvent } from 'react'

import { ScrollArea, ScrollBar } from 'lib/ui/quill'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowTreeNode } from './HogFlowTreeNode'
import { buildWorkflowTree } from './workflowTree'

export function HogFlowTreeEditor(): JSX.Element {
    const { nodeToBeAdded, workflow } = useValues(hogFlowEditorLogic)
    const [draggedActionId, setDraggedActionId] = useState<string | null>(null)
    const tree = useMemo(() => buildWorkflowTree(workflow), [workflow])
    const activeDropzones = !!nodeToBeAdded || !!draggedActionId

    const onDragStart = (event: DragEvent<HTMLDivElement>, actionId: string): void => {
        setDraggedActionId(actionId)
        event.dataTransfer.effectAllowed = 'move'
        event.dataTransfer.setData('text/plain', actionId)
    }

    return (
        <ScrollArea className="min-h-0 min-w-0 flex-1 bg-background" data-quill data-attr="workflow-tree-editor">
            <div className="mx-auto flex w-full max-w-3xl flex-col p-4">
                {tree.nodes.map((node) => (
                    <HogFlowTreeNode
                        key={node.action.id}
                        node={node}
                        activeDropzones={activeDropzones}
                        draggedActionId={draggedActionId}
                        onDragStart={onDragStart}
                        onDragEnd={() => setDraggedActionId(null)}
                    />
                ))}
            </div>
            <ScrollBar orientation="vertical" />
        </ScrollArea>
    )
}
