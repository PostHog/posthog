import { IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonLabel } from '@posthog/lemon-ui'
import { getOutgoers, Node, Panel, useEdges, useNodes } from '@xyflow/react'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { WorkflowNodeData } from '../temporary_workflow_types_for_dev_to_be_deleted'

export function StepDetailsPanel({
    node,
    onDelete,
    onClose,
}: {
    workflowId: string
    node: Node<WorkflowNodeData>
    onChange: (node: Node<WorkflowNodeData>) => void
    onDelete: (node: Node<WorkflowNodeData>) => void
    onClose: () => void
}): JSX.Element {
    const nodes = useNodes()
    const edges = useEdges()

    const canBeDeleted = (): boolean => {
        const outgoingNodes = getOutgoers(node, nodes, edges)
        if (outgoingNodes.length === 1) {
            return true
        }

        return new Set(outgoingNodes.map((node) => node.id)).size === 1
    }

    return (
        <Panel position="top-right">
            <div className="bg-surface-primary rounded-md shadow-md p-4 gap-2 flex flex-col z-10 w-[300px]">
                <div className="flex items-center justify-between">
                    <h3 className="font-semibold">Edit {node.data.label} step</h3>
                    <div className="flex items-center gap-1">
                        {node.deletable && (
                            <LemonButton
                                size="small"
                                status="danger"
                                onClick={() => onDelete(node)}
                                icon={<IconTrash />}
                                disabledReason={canBeDeleted() ? undefined : 'Clean up branching steps first'}
                            />
                        )}
                        <LemonButton size="small" icon={<IconX />} onClick={onClose} aria-label="close" />
                    </div>
                </div>
                {/* TODO: Add dynamic form using renderer like HogFunctionInputs */}
                <LemonLabel>Name</LemonLabel>
                <LemonInput />
            </div>
        </Panel>
    )
}
