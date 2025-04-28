import { IconMessage, IconSend, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { llmObservabilityLogic } from './llmObservabilityLogic'
import { llmObservabilityPlaygroundLogic } from './llmObservabilityPlaygroundLogic'
import { ModelOption } from './llmObservabilityPlaygroundLogic'

export const scene: SceneExport = {
    component: LLMObservabilityPlaygroundScene,
    logic: llmObservabilityLogic,
}

export function LLMObservabilityPlaygroundScene(): JSX.Element {
    return (
        <BindLogic logic={llmObservabilityPlaygroundLogic} props={{ key: 'llm-observability-playground' }}>
            <div>
                <PlaygroundContent />
            </div>
        </BindLogic>
    )
}

function PlaygroundContent(): JSX.Element {
    return (
        <div className="flex flex-col space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <PromptPanel />
                <ResponsePanel />
            </div>
        </div>
    )
}

function ModelSelector(): JSX.Element {
    const { model, modelOptions, modelOptionsLoading } = useValues(llmObservabilityPlaygroundLogic)
    const { setModel } = useActions(llmObservabilityPlaygroundLogic)

    // Ensure modelOptions is an array before mapping
    const options = Array.isArray(modelOptions) ? modelOptions : []

    return (
        <div className="mb-4">
            <label className="font-semibold mb-1 block">Model</label>
            <LemonSelect
                className="w-full"
                placeholder="Select model"
                value={model}
                onChange={(value) => setModel(value)}
                options={options.map((option: ModelOption) => ({
                    label: `${option.name} (${option.provider})`,
                    value: option.id,
                    tooltip: option.description,
                }))}
                loading={modelOptionsLoading}
                disabled={modelOptionsLoading}
            />
        </div>
    )
}

function PromptPanel(): JSX.Element {
    const { prompt, systemPrompt, temperature, maxTokens, thinking } = useValues(llmObservabilityPlaygroundLogic)
    const { setPrompt, setSystemPrompt, setTemperature, setMaxTokens, setThinking, submitPrompt, clearConversation } =
        useActions(llmObservabilityPlaygroundLogic)

    const handleSubmit = (e: React.FormEvent): void => {
        e.preventDefault()
        submitPrompt()
    }

    const handleThinkingToggle = (e: React.ChangeEvent<HTMLInputElement>): void => {
        setThinking(e.target.checked)
    }

    return (
        <div className="rounded border p-4 flex flex-col h-[700px]">
            <h3 className="text-base font-semibold mb-2">Input</h3>
            <div className="mb-4">
                <label className="font-semibold mb-1 block">System Prompt</label>
                <LemonTextArea
                    className="h-16 text-xs"
                    placeholder="Instructions for the AI assistant..."
                    value={systemPrompt}
                    onChange={(e) => setSystemPrompt(e)}
                />
            </div>

            <ModelSelector />

            <div className="grid grid-cols-2 gap-4 mb-4">
                <div>
                    <label className="font-semibold mb-1 block">Temperature: {temperature.toFixed(1)}</label>
                    <LemonInput
                        type="number"
                        min={0.0}
                        max={1.0}
                        step={0.1}
                        value={temperature}
                        onChange={(value) => setTemperature(Number(value))}
                    />
                    <div className="text-xs text-muted mt-1 flex justify-between">
                        <span>Precise</span>
                        <span>Creative</span>
                    </div>
                </div>
                <div>
                    <label className="font-semibold mb-1 block">Max tokens</label>
                    <LemonInput
                        type="number"
                        value={maxTokens}
                        onChange={(value) => setMaxTokens(Number(value))}
                        min={1}
                        max={8192}
                    />
                </div>
            </div>

            <div className="mb-4 flex items-center space-x-2">
                <input id="thinkingToggle" type="checkbox" checked={thinking} onChange={handleThinkingToggle} />
                <label htmlFor="thinkingToggle" className="text-sm">
                    Enable thinking mode
                </label>
            </div>

            <form className="flex items-end gap-2" onSubmit={handleSubmit}>
                <LemonTextArea
                    className="flex-1"
                    placeholder="Enter your prompt..."
                    value={prompt}
                    onChange={(value) => setPrompt(value)}
                />
                <div className="flex flex-col gap-2">
                    <LemonButton
                        type="primary"
                        icon={<IconSend />}
                        htmlType="submit"
                        disabledReason={!prompt.trim() ? 'Enter a prompt' : undefined}
                    />
                    <LemonButton
                        type="secondary"
                        status="danger"
                        tooltip="Clear conversation"
                        icon={<IconTrash />}
                        onClick={clearConversation}
                    />
                </div>
            </form>
        </div>
    )
}

function ResponsePanel(): JSX.Element {
    const { messages } = useValues(llmObservabilityPlaygroundLogic)

    return (
        <div className="rounded border p-4 flex flex-col h-[700px]">
            <h3 className="text-base font-semibold mb-2">Output</h3>

            <div className="flex-1 overflow-y-auto border rounded p-2">
                {messages.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-muted">
                        <IconMessage className="text-3xl mb-2" />
                        <p>Enter a prompt to generate a response</p>
                    </div>
                ) : (
                    <>
                        <div className="font-semibold text-xs mb-2">Conversation</div>
                        <ConversationOutput messages={messages} />
                    </>
                )}
            </div>
        </div>
    )
}

function ConversationOutput({ messages }: { messages: { role: string; content: string }[] }): JSX.Element {
    return (
        <div className="space-y-3">
            {messages.map((message, index) => (
                <div key={index} className="flex items-start">
                    <div className="flex-1">
                        <div className="font-semibold text-xs capitalize">{message.role}</div>
                        <div className="whitespace-pre-wrap text-sm">{message.content}</div>
                    </div>
                </div>
            ))}
        </div>
    )
}
