import { IconTrash, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { getOutgoers, Node, Panel, useEdges, useNodes } from '@xyflow/react'
import { Form } from 'kea-forms'
import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { useMemo } from 'react'

import type { HogFlowAction } from '../types'
import { HogFlowActionManager } from './hogFlowActionManager'
import { nodeLogic } from './nodeLogic'

export function ActionDetailsPanel({
    node,
    onChange,
    onDelete,
    onClose,
}: {
    node: Node<HogFlowAction>
    onChange: (node: Node<HogFlowAction>) => void
    onDelete: (node: Node<HogFlowAction>) => void
    onClose: () => void
}): JSX.Element {
    const nodes = useNodes()
    const edges = useEdges()

    // eslint-disable-next-line react-hooks/exhaustive-deps
    const hogFlowAction = useMemo(() => HogFlowActionManager.fromReactFlowNode(node), [node.data])

    const canBeDeleted = (): boolean => {
        const outgoingNodes = getOutgoers(node, nodes, edges)
        if (outgoingNodes.length === 1) {
            return true
        }

        return new Set(outgoingNodes.map((node) => node.id)).size === 1
    }

    const handleInputChange = (key: string, value: any): void => {
        hogFlowAction.setInput(key, value)
        onChange(hogFlowAction.toReactFlowNode())
    }

    return (
        <Panel position="top-right">
            <Form
                logic={nodeLogic}
                props={{ node }}
                formKey="inputs"
                className="bg-surface-primary rounded-md shadow-md p-4 gap-2 flex flex-col z-10 min-w-[300px] max-w-[500px] max-h-3/4 overflow-y-scroll"
            >
                <div className="flex justify-between items-center">
                    <h3 className="font-semibold">Edit {hogFlowAction.action.name} step</h3>
                    <div className="flex gap-1 items-center">
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
                <div className="flex flex-col gap-2">
                    <CyclotronJobInputs
                        configuration={{
                            inputs: hogFlowAction.getInputs(),
                            inputs_schema: hogFlowAction.getInputsSchema(),
                        }}
                        onInputChange={handleInputChange}
                        showSource={false}
                    />
                </div>
            </Form>
        </Panel>
    )
}
