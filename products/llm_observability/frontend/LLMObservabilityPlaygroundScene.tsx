import { IconGear, IconMessage, IconPlay, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { llmObservabilityPlaygroundLogic } from './llmObservabilityPlaygroundLogic'
import { ComparisonItem, Message, MessageRole, ModelOption } from './llmObservabilityPlaygroundLogic'

// Helper to format milliseconds
const formatMs = (ms: number | null | undefined): string => {
    if (ms === null || typeof ms === 'undefined') {
        return '-'
    }
    if (ms < 1000) {
        return `${ms.toFixed(0)} ms`
    }
    return `${(ms / 1000).toFixed(2)} s`
}

export const scene: SceneExport = {
    component: LLMObservabilityPlaygroundScene,
    logic: llmObservabilityPlaygroundLogic,
}

export function LLMObservabilityPlaygroundScene(): JSX.Element {
    return (
        <BindLogic logic={llmObservabilityPlaygroundLogic} props={{ key: 'llm-observability-playground-scene' }}>
            <PlaygroundLayout />
        </BindLogic>
    )
}

function PlaygroundLayout(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 min-h-[calc(100vh-120px)]">
            <div className="flex gap-4 flex-1 h-[calc(100vh-120px)]">
                <div className="w-1/2 flex flex-col border rounded p-4 overflow-hidden">
                    <h3 className="text-lg font-semibold mb-4 shrink-0">Input</h3>
                    <InputPanel />
                </div>

                <div className="w-1/2 flex flex-col border rounded overflow-hidden">
                    <OutputPanel />
                </div>
            </div>

            <ComparisonTablePanel />
        </div>
    )
}

function InputPanel(): JSX.Element {
    const { messages, submitting } = useValues(llmObservabilityPlaygroundLogic)
    const { addMessage, clearConversation } = useActions(llmObservabilityPlaygroundLogic)
    const scrollRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
    }, [messages])

    return (
        <div className="flex-1 flex flex-col overflow-hidden">
            <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 pr-2 mb-3">
                {messages.map((message, index) => (
                    <MessageEditor key={index} index={index} message={message} />
                ))}
                {messages.length === 0 && (
                    <div className="flex flex-col items-center justify-center h-full text-muted">
                        <IconMessage className="text-3xl mb-2" />
                        <p>Add messages to start the conversation.</p>
                    </div>
                )}
            </div>
            <div className="flex gap-2 pt-2 border-t shrink-0">
                <LemonButton type="secondary" icon={<IconPlus />} onClick={() => addMessage()} disabled={submitting}>
                    Add Message
                </LemonButton>
                <LemonButton
                    type="secondary"
                    status="danger"
                    icon={<IconTrash />}
                    onClick={clearConversation}
                    disabled={submitting || messages.length === 0}
                    tooltip="Clear all messages"
                    className="ml-auto"
                >
                    Clear All
                </LemonButton>
            </div>
        </div>
    )
}

function MessageEditor({ message, index }: { message: Message; index: number }): JSX.Element {
    const { updateMessage, deleteMessage } = useActions(llmObservabilityPlaygroundLogic)

    const handleRoleChange = (newRole: MessageRole): void => {
        updateMessage(index, { role: newRole })
    }

    const handleContentChange = (newContent: string): void => {
        updateMessage(index, { content: newContent })
    }

    const roleOptions: { label: string; value: MessageRole }[] = [
        { label: 'Human', value: 'user' },
        { label: 'AI', value: 'assistant' },
        { label: 'System', value: 'system' },
    ]

    return (
        <div className="border rounded p-3 relative group bg-bg-light dark:bg-bg-dark">
            <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <LemonButton
                    size="small"
                    status="danger"
                    icon={<IconTrash />}
                    tooltip="Delete message"
                    noPadding
                    onClick={() => deleteMessage(index)}
                />
            </div>
            <div className="flex items-center gap-2 mb-2">
                <LemonSelect<MessageRole>
                    size="small"
                    options={roleOptions}
                    value={message.role}
                    onChange={handleRoleChange}
                    dropdownMatchSelectWidth={false}
                />
            </div>
            <LemonTextArea
                className="text-sm w-full"
                placeholder={`Enter ${message.role} message here...`}
                value={message.content}
                onChange={handleContentChange}
                minRows={2}
            />
        </div>
    )
}

function OutputPanel(): JSX.Element {
    const { submitting, currentResponse, model, lastRunDetails, messages } = useValues(llmObservabilityPlaygroundLogic)
    const { submitPrompt, addResponseToHistory, addCurrentRunToComparison } = useActions(
        llmObservabilityPlaygroundLogic
    )
    const [configOpen, setConfigOpen] = useState(true)

    let runDisabledReason = undefined
    if (messages.length === 0) {
        runDisabledReason = 'Add messages to start the conversation'
    }

    return (
        <div className="flex-1 flex flex-col h-full">
            <div className="flex justify-between items-center p-2 border-b shrink-0 gap-2">
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="primary"
                        icon={<IconPlay />}
                        onClick={submitPrompt}
                        loading={submitting}
                        disabledReason={submitting ? 'Generating...' : runDisabledReason}
                    >
                        Run
                    </LemonButton>
                    {model && <div className="text-sm text-muted">{model}</div>}
                </div>
                <LemonButton
                    type="secondary"
                    icon={<IconGear />}
                    onClick={() => setConfigOpen(!configOpen)}
                    active={configOpen}
                    tooltip={configOpen ? 'Hide configuration' : 'Show configuration'}
                >
                    Toggle Config
                </LemonButton>
            </div>

            {configOpen && (
                <div className="p-4 border-b overflow-y-auto shrink-0">
                    <ConfigurationPanel />
                </div>
            )}

            {/* Output Display Area */}
            <div className="flex-1 overflow-y-auto p-4">
                {' '}
                {/* Scrollable output */}
                <h3 className="text-base font-semibold mb-2 text-muted">AI Output</h3>
                {submitting && (currentResponse === null || currentResponse === '') && (
                    <LemonSkeleton active className="my-2" />
                )}
                {currentResponse && (
                    <pre className="whitespace-pre-wrap text-sm break-words">
                        {currentResponse}
                        {submitting && <span className="text-muted italic"> (streaming...)</span>}
                    </pre>
                )}
                <div className="flex gap-2">
                    {!submitting && currentResponse && currentResponse.trim() && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => addResponseToHistory(currentResponse)}
                            className="mt-2"
                        >
                            Add to Chat History
                        </LemonButton>
                    )}

                    {/* Button to add response to comparison */}
                    {!submitting && lastRunDetails && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            className="mt-2"
                            onClick={addCurrentRunToComparison}
                            tooltip={
                                !lastRunDetails
                                    ? 'Run the prompt first to enable comparison'
                                    : 'Add this run to comparison table'
                            }
                        >
                            Add to Compare
                        </LemonButton>
                    )}
                </div>
            </div>
        </div>
    )
}

function ConfigurationPanel(): JSX.Element {
    const { systemPrompt, temperature, maxTokens, thinking, model, modelOptions, modelOptionsLoading } = useValues(
        llmObservabilityPlaygroundLogic
    )
    const { setSystemPrompt, setTemperature, setMaxTokens, setThinking, setModel } = useActions(
        llmObservabilityPlaygroundLogic
    )

    const handleThinkingToggle = (e: React.ChangeEvent<HTMLInputElement>): void => {
        setThinking(e.target.checked)
    }

    const options = Array.isArray(modelOptions) ? modelOptions : []

    return (
        <div className="space-y-4">
            <div>
                <label className="font-semibold mb-1 block text-sm">Model</label>
                {modelOptionsLoading && !options.length ? (
                    <LemonSkeleton className="h-10" />
                ) : (
                    <LemonSelect
                        className="w-full"
                        placeholder="Select model"
                        value={model}
                        onChange={(value) => setModel(value)}
                        options={options.map((option: ModelOption) => ({
                            label: `${option.name} (${option.provider})`,
                            value: option.id,
                            tooltip: option.description || `Provider: ${option.provider}`,
                        }))}
                        loading={modelOptionsLoading}
                        disabled={modelOptionsLoading || options.length === 0}
                    />
                )}
                {options.length === 0 && !modelOptionsLoading && (
                    <p className="text-xs text-danger mt-1">No models available. Check proxy status.</p>
                )}
            </div>

            <div>
                <label className="font-semibold mb-1 block text-sm">System Prompt</label>
                <LemonTextArea
                    className="text-sm"
                    placeholder="Instructions for the AI assistant..."
                    value={systemPrompt}
                    onChange={(val) => setSystemPrompt(val)}
                    rows={3}
                />
            </div>

            <div className="grid grid-cols-2 gap-4">
                <div>
                    <label className="font-semibold mb-1 block text-sm">Temperature: {temperature.toFixed(1)}</label>
                    <input
                        type="range"
                        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
                        min={0.0}
                        max={1.0}
                        step={0.1}
                        value={temperature}
                        onChange={(e) => setTemperature(Number(e.target.value))}
                    />
                    <div className="text-xs text-muted mt-1 flex justify-between">
                        <span>Precise</span>
                        <span>Creative</span>
                    </div>
                </div>
                <div>
                    <label className="font-semibold mb-1 block text-sm">Max tokens</label>
                    <LemonInput
                        type="number"
                        value={maxTokens}
                        onChange={(val) => setMaxTokens(Number(val))}
                        min={1}
                        max={16384}
                        step={64}
                    />
                </div>
            </div>

            <div className="flex items-center space-x-2">
                <input
                    id="thinkingToggle"
                    type="checkbox"
                    className="rounded text-primary focus:ring-primary"
                    checked={thinking}
                    onChange={handleThinkingToggle}
                />
                <label htmlFor="thinkingToggle" className="text-sm font-medium">
                    Enable thinking/reasoning stream (if supported)
                </label>
            </div>
        </div>
    )
}

function ComparisonTablePanel(): JSX.Element {
    const { comparisonItems } = useValues(llmObservabilityPlaygroundLogic)
    const { clearComparison } = useActions(llmObservabilityPlaygroundLogic)

    // Define columns for the LemonTable
    const columns: LemonTableColumns<ComparisonItem> = [
        {
            title: 'Model',
            dataIndex: 'model',
            render: (model) => <LemonTag>{typeof model === 'string' ? model || '-' : '-'}</LemonTag>,
            sorter: (a, b) => a.model.localeCompare(b.model),
        },
        {
            title: 'Response',
            dataIndex: 'response',
            render: (response) => (
                <div className="max-h-40 overflow-y-auto whitespace-pre-wrap text-xs break-words p-1 border rounded bg-bg-light dark:bg-bg-dark">
                    {typeof response === 'string' ? response : '-'}
                </div>
            ),
            width: '40%',
        },
        {
            title: 'TTFT',
            dataIndex: 'ttftMs',
            render: (ttftMs) => formatMs(ttftMs as number | null),
            sorter: (a, b) => (a.ttftMs ?? Infinity) - (b.ttftMs ?? Infinity),
            align: 'right',
            tooltip: 'Time To First Token',
        },
        {
            title: 'Latency',
            dataIndex: 'latencyMs',
            render: (latencyMs) => formatMs(latencyMs as number | null),
            sorter: (a, b) => (a.latencyMs ?? Infinity) - (b.latencyMs ?? Infinity),
            align: 'right',
            tooltip: 'Total Request Latency',
        },
    ]

    if (comparisonItems.length === 0) {
        return <></> // Return empty fragment instead of null
    }

    return (
        <div className="border rounded p-4 min-h-0 flex flex-col">
            <div className="flex justify-between items-center mb-4 shrink-0">
                <h3 className="text-lg font-semibold">Comparison</h3>
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    icon={<IconTrash />}
                    onClick={clearComparison}
                    tooltip="Clear all comparison items"
                >
                    Clear All
                </LemonButton>
            </div>
            {/* Use flex-1 on the table container to make it fill remaining space */}
            <div className="flex-1 overflow-hidden">
                <LemonTable
                    dataSource={comparisonItems}
                    columns={columns}
                    rowKey="id"
                    loading={false} // Add loading state if needed
                    embedded // Use embedded style for tighter spacing
                />
            </div>
        </div>
    )
}
