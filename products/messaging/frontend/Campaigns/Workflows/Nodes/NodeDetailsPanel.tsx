import { IconTrash, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { getOutgoers, Node, Panel, useEdges, useNodes } from '@xyflow/react'
import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'

import type { HogFlowAction } from '../types'
import { Form } from 'kea-forms'
import { campaignLogic } from '../../campaignLogic'

export function NodeDetailsPanel({
    node,
    onChange,
    onDelete,
    onClose,
}: {
    workflowId: string
    node: Node<HogFlowAction>
    onChange: (node: Node<HogFlowAction>) => void
    onDelete: (node: Node<HogFlowAction>) => void
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

    const config = node.data || {}

    const handleInputChange = (key: string, value: any): void => {
        onChange({
            ...node,
            data: {
                ...node.data,
                inputs: {
                    ...config.inputs,
                    [key]: value,
                },
            },
        })
    }

    return (
        <Panel position="top-right">
            <Form
                logic={campaignLogic}
                props={node}
                formKey="campaign"
                className="bg-surface-primary rounded-md shadow-md p-4 gap-2 flex flex-col z-10 min-w-[300px] max-w-[500px] max-h-3/4 overflow-y-scroll"
            >
                <div className="flex items-center justify-between">
                    <h3 className="font-semibold">Edit {node.data.name} step</h3>
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
                <div className="flex flex-col gap-2">
                    <CyclotronJobInputs
                        configuration={config}
                        setConfigurationValue={handleInputChange}
                        showSource={false}
                    />
                </div>
            </Form>
        </Panel>
    )
}
