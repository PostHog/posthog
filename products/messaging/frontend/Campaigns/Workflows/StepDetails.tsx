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

                    {node.type === 'trigger' && (
                        <LemonField name="config.triggerType" label="Trigger Type">
                            <LemonSelect
                                options={[
                                    { label: 'Email', value: 'email' },
                                    { label: 'SMS', value: 'sms' },
                                    { label: 'Push', value: 'push' },
                                ]}
                            />
                        </LemonField>
                    )}
                    {node.type === 'action' && (
                        <LemonField name="config.actionType" label="Action Type">
                            <LemonSelect
                                options={[
                                    { label: 'Send Email', value: 'send_email' },
                                    { label: 'Send SMS', value: 'send_sms' },
                                    { label: 'Send Push', value: 'send_push' },
                                ]}
                            />
                        </LemonField>
                    )}
                    {node.type === 'condition' && (
                        <LemonField name="config.conditionType" label="Condition Type">
                            <LemonSelect
                                options={[
                                    { label: 'Has Opened', value: 'has_opened' },
                                    { label: 'Has Clicked', value: 'has_clicked' },
                                    { label: 'Has Responded', value: 'has_responded' },
                                ]}
                            />
                        </LemonField>
                    )}
                </Form>
            </div>
        </Panel>
    )
}
