import { IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { WorkflowNodeData } from '@posthog/workflows'
import { Node, Panel } from '@xyflow/react'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { stepDetailsLogic } from './stepDetailsLogic'

export function StepDetailsPanel({
    workflowId,
    node,
    onChange,
    onDelete,
    onClose,
}: {
    workflowId: string
    node: Node<WorkflowNodeData>
    onChange: (node: Node<WorkflowNodeData>) => void
    onDelete: (node: Node<WorkflowNodeData>) => void
    onClose: () => void
}): JSX.Element {
    const _foo = useValues(
        stepDetailsLogic({
            workflowId,
            node,
            onChange,
        })
    )

    return (
        <Panel position="top-right">
            <div className="bg-surface-primary rounded-md shadow-md p-4 gap-2 flex flex-col z-10 w-[300px]">
                <div className="flex items-center justify-between">
                    <h3 className="font-semibold">Edit {node.data.label} step</h3>
                    <div className="flex items-center gap-1">
                        {!['trigger', 'exit'].includes(node.type || '') && (
                            <LemonButton
                                size="small"
                                status="danger"
                                onClick={() => onDelete(node)}
                                icon={<IconTrash />}
                            />
                        )}
                        <LemonButton size="small" icon={<IconX />} onClick={onClose} aria-label="close" />
                    </div>
                </div>
                <Form logic={stepDetailsLogic} formKey="step">
                    <LemonField name="label" label="Name">
                        <LemonInput />
                    </LemonField>
                </Form>
            </div>
        </Panel>
    )
}
