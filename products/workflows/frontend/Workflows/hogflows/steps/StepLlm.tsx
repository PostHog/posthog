import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { IconGear, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput, LemonLabel, LemonSelect, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { ModelPicker, getModelPickerFooterLink } from 'products/ai_observability/frontend/ModelPicker'
import { modelPickerLogic } from 'products/ai_observability/frontend/modelPickerLogic'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'

type LlmAction = Extract<HogFlowAction, { type: 'llm' }>
type LlmMessage = LlmAction['config']['messages'][number]
type ReasoningEffort = 'minimal' | 'low' | 'medium' | 'high'

const ROLE_OPTIONS: { value: LlmMessage['role']; label: string }[] = [
    { value: 'system', label: 'System' },
    { value: 'user', label: 'User' },
    { value: 'assistant', label: 'Assistant' },
]

// Model picker reused from AI observability, so the workflow step matches the Playground UX. Stores
// just the model id on the step - the gateway routes by model, so no provider key is threaded here.
function LlmModelPicker({ action }: { action: LlmAction }): JSX.Element {
    const { logicProps } = useValues(workflowLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic(logicProps))
    const { hasByokKeys, providerModelGroups, trialProviderModelGroups, byokModelsLoading, trialModelsLoading, providerKeysLoading } =
        useValues(modelPickerLogic)

    const groups = hasByokKeys ? providerModelGroups : trialProviderModelGroups
    const loading = hasByokKeys ? byokModelsLoading || providerKeysLoading : trialModelsLoading
    const selectedModelName = groups.flatMap((g) => g.models).find((m) => m.id === action.config.model)?.name

    return (
        <ModelPicker
            model={action.config.model}
            selectedProviderKeyId={null}
            onSelect={(modelId) => partialSetWorkflowActionConfig(action.id, { model: modelId })}
            groups={groups}
            loading={loading}
            footerLink={getModelPickerFooterLink(hasByokKeys)}
            selectedModelName={selectedModelName}
            data-attr="workflow-llm-model-selector"
        />
    )
}

function LlmSettingsOverlay({ action }: { action: LlmAction }): JSX.Element {
    const { logicProps } = useValues(workflowLogic)
    const { partialSetWorkflowActionConfig } = useActions(workflowLogic(logicProps))
    const { max_tokens, temperature, top_p, reasoning_effort, thinking } = action.config

    const set = (patch: Partial<LlmAction['config']>): void => partialSetWorkflowActionConfig(action.id, patch)

    return (
        <div className="space-y-4 p-4 w-[300px]">
            <div>
                <label className="text-xs font-medium mb-1 block">Max tokens</label>
                <LemonInput
                    type="number"
                    value={max_tokens ?? undefined}
                    onChange={(val) => set({ max_tokens: val ?? undefined })}
                    min={1}
                    max={16384}
                    step={64}
                    placeholder="Model default"
                    size="small"
                />
            </div>
            <div>
                <label className="text-xs font-medium mb-1 block">Temperature</label>
                <LemonInput
                    type="number"
                    value={temperature ?? undefined}
                    onChange={(val) => set({ temperature: val ?? undefined })}
                    min={0}
                    max={2}
                    step={0.1}
                    placeholder="Model default"
                    size="small"
                />
            </div>
            <div>
                <label className="text-xs font-medium mb-1 block">Top p</label>
                <LemonInput
                    type="number"
                    value={top_p ?? undefined}
                    onChange={(val) => set({ top_p: val ?? undefined })}
                    min={0}
                    max={1}
                    step={0.05}
                    placeholder="Model default"
                    size="small"
                />
            </div>
            <div>
                <label className="text-xs font-medium mb-1 block">Reasoning effort</label>
                <LemonSelect<ReasoningEffort | null>
                    size="small"
                    placeholder="None"
                    value={reasoning_effort ?? null}
                    onChange={(value) => set({ reasoning_effort: value ?? undefined })}
                    options={[
                        { label: 'None', value: null },
                        { label: 'Minimal', value: 'minimal' },
                        { label: 'Low', value: 'low' },
                        { label: 'Medium', value: 'medium' },
                        { label: 'High', value: 'high' },
                    ]}
                    fullWidth
                    dropdownMatchSelectWidth={false}
                />
            </div>
            <LemonSwitch
                bordered
                checked={!!thinking}
                onChange={(checked) => set({ thinking: checked })}
                label="Thinking"
                size="small"
                tooltip="Enable extended thinking (model must support it)"
            />
        </div>
    )
}

export function StepLlmConfiguration({ node }: { node: Node<LlmAction> }): JSX.Element {
    const action = node.data
    const { messages, max_wait_duration } = action.config

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

            <div className="flex flex-wrap items-center gap-2">
                <div className="flex-1 min-w-[220px]">
                    <LlmModelPicker action={action} />
                </div>
                <LemonDropdown
                    overlay={<LlmSettingsOverlay action={action} />}
                    closeOnClickInside={false}
                    placement="bottom-end"
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconGear />}
                        tooltip="Max tokens, temperature, thinking, reasoning"
                    >
                        Settings
                    </LemonButton>
                </LemonDropdown>
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
                <LemonLabel info="If the model hasn't responded within this time, the step takes its error path. Set it above the model's expected response time.">
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
