import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'

type LlmAction = Extract<HogFlowAction, { type: 'llm' }>
type LlmMessage = LlmAction['config']['messages'][number]

const ROLE_OPTIONS: { value: LlmMessage['role']; label: string }[] = [
    { value: 'system', label: 'System' },
    { value: 'user', label: 'User' },
    { value: 'assistant', label: 'Assistant' },
]

export function StepLlmConfiguration({ node }: { node: Node<LlmAction> }): JSX.Element {
    const action = node.data
    const { model, messages, max_wait_duration } = action.config

    const { logicProps } = useValues(workflowLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic(logicProps))

    const updateMessages = (next: LlmMessage[]): void => {
        partialSetWorkflowActionConfig(action.id, { messages: next })
    }

    const addMessage = (): void => {
        updateMessages([...messages, { role: 'user', content: { value: '', templating: 'liquid' } }])
    }

    return (
        <>
            <StepSchemaErrors />

            <p className="mb-0">Send a prompt to an LLM and store the response in a workflow variable.</p>

            <div className="flex flex-col gap-1">
                <LemonLabel>Model</LemonLabel>
                <LemonInput
                    value={model}
                    onChange={(value) => partialSetWorkflowActionConfig(action.id, { model: value })}
                    placeholder="e.g. openai/gpt-4o-mini"
                />
            </div>

            <div className="flex flex-col gap-2">
                <LemonLabel>Prompt</LemonLabel>
                {messages.map((message, index) => (
                    <div key={index} className="flex flex-col gap-1 rounded border p-2">
                        <div className="flex items-center justify-between">
                            <LemonSelect
                                size="small"
                                value={message.role}
                                options={ROLE_OPTIONS}
                                onChange={(role) => {
                                    const next = [...messages]
                                    next[index] = { ...message, role }
                                    updateMessages(next)
                                }}
                            />
                            {messages.length > 1 && (
                                <LemonButton
                                    size="small"
                                    icon={<IconTrash />}
                                    onClick={() => updateMessages(messages.filter((_, i) => i !== index))}
                                    tooltip="Remove message"
                                />
                            )}
                        </div>
                        <LemonTextArea
                            value={typeof message.content?.value === 'string' ? message.content.value : ''}
                            onChange={(value) => {
                                const next = [...messages]
                                // Default to liquid templating so {{ variables.x }} / {{ event.properties.y }} render.
                                next[index] = { ...message, content: { value, templating: 'liquid' } }
                                updateMessages(next)
                            }}
                            placeholder="Write the prompt. Reference workflow state with {{ variables.x }} or {{ event.properties.y }}."
                            minRows={3}
                        />
                    </div>
                ))}
                <LemonButton size="small" type="secondary" icon={<IconPlus />} onClick={addMessage}>
                    Add message
                </LemonButton>
            </div>

            <div className="flex flex-col gap-1">
                <LemonLabel
                    info="If the model hasn't responded within this time, the step takes its error path. Set it above the model's expected response time."
                >
                    Max time to wait
                </LemonLabel>
                <HogFlowDuration
                    value={max_wait_duration}
                    onChange={(value) => partialSetWorkflowActionConfig(action.id, { max_wait_duration: value })}
                />
            </div>
        </>
    )
}
