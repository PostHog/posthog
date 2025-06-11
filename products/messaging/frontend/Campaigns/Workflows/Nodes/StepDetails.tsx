import { IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { getOutgoers, Node, Panel, useEdges, useNodes } from '@xyflow/react'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { z } from 'zod'

import type { HogFlowAction } from '../types'
import { CyclotronJobInputSchema } from '../types'

type CyclotronJobInputSchemaType = z.infer<typeof CyclotronJobInputSchema>

interface Choice {
    value: string
    label: string
}

const getStepInputSchema = (type: HogFlowAction['type']): CyclotronJobInputSchemaType[] => {
    switch (type) {
        case 'message':
            return [
                {
                    type: 'string',
                    key: 'name',
                    label: 'Name',
                    required: true,
                },
                {
                    type: 'string',
                    key: 'subject',
                    label: 'Subject',
                    required: true,
                },
                {
                    type: 'string',
                    key: 'content',
                    label: 'Content',
                    required: true,
                },
            ]
        case 'delay':
            return [
                {
                    type: 'string',
                    key: 'name',
                    label: 'Name',
                    required: true,
                },
                {
                    type: 'string',
                    key: 'duration',
                    label: 'Duration (minutes)',
                    required: true,
                },
            ]
        case 'conditional_branch':
            return [
                {
                    type: 'string',
                    key: 'name',
                    label: 'Name',
                    required: true,
                },
                {
                    type: 'string',
                    key: 'condition',
                    label: 'Condition',
                    required: true,
                },
            ]
        default:
            return [
                {
                    type: 'string',
                    key: 'name',
                    label: 'Name',
                    required: true,
                },
            ]
    }
}

export function StepDetailsPanel({
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

    const inputSchema = getStepInputSchema(node.data.type)
    const config = node.data.config || {}

    const handleInputChange = (key: string, value: any): void => {
        onChange({
            ...node,
            data: {
                ...node.data,
                config: {
                    ...config,
                    [key]: value,
                },
            },
        })
    }

    return (
        <Panel position="top-right">
            <div className="bg-surface-primary rounded-md shadow-md p-4 gap-2 flex flex-col z-10 w-[300px]">
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
                    {inputSchema.map((input) => (
                        <div key={input.key} className="flex flex-col gap-1">
                            <LemonLabel>{input.label}</LemonLabel>
                            {input.type === 'string' && (
                                <LemonInput
                                    value={config[input.key] || ''}
                                    onChange={(value) => handleInputChange(input.key, value)}
                                />
                            )}
                            {input.type === 'boolean' && (
                                <LemonSwitch
                                    checked={config[input.key] || false}
                                    onChange={(checked) => handleInputChange(input.key, checked)}
                                />
                            )}
                            {input.type === 'choice' && input.choices && (
                                <LemonSelect
                                    value={config[input.key] || ''}
                                    onChange={(value) => handleInputChange(input.key, value)}
                                    options={input.choices.map((choice: Choice) => ({
                                        value: choice.value,
                                        label: choice.label,
                                    }))}
                                />
                            )}
                        </div>
                    ))}
                </div>
            </div>
        </Panel>
    )
}
