import { IconGear, IconMessage, IconPencil, IconPlay, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { useRef, useState } from 'react'
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
        <div className="flex flex-col min-h-[calc(100vh-120px)] relative">
            {/* Main conversation area - full width */}
            <div className="flex flex-col border rounded overflow-hidden flex-1">
                <ConversationPanel />
            </div>

            {/* Comparison table - only show if there are items */}
            <ComparisonTablePanel />

            {/* Sticky action bar at bottom */}
            <StickyActionBar />
        </div>
    )
}

function ConversationPanel(): JSX.Element {
    const { messages } = useValues(llmObservabilityPlaygroundLogic)
    const [expandTextAreas, setExpandTextAreas] = useState(false)
    const messagesStartRef = useRef<HTMLDivElement>(null)
    const messagesEndRef = useRef<HTMLDivElement>(null)

    return (
        <>
            {/* Messages area */}
            <div className="flex-1 p-4">
                <div ref={messagesStartRef} data-attr="messages-start" />
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold">Messages</h3>
                    <LemonSwitch
                        bordered
                        checked={expandTextAreas}
                        onChange={setExpandTextAreas}
                        label="Expand text areas"
                        size="small"
                        tooltip="If your messages exceed the text box you can toggle this to see more"
                    />
                </div>
                <div className="space-y-3">
                    <SystemMessageDisplay expandTextAreas={expandTextAreas} />
                    {messages.map((message, index) => (
                        <MessageDisplay key={index} index={index} message={message} expandTextAreas={expandTextAreas} />
                    ))}
                    {messages.length === 0 && (
                        <div className="flex flex-col items-center justify-center py-12 text-tertiary-foreground">
                            <IconMessage className="text-3xl mb-2" />
                            <p>Add messages to start the conversation.</p>
                        </div>
                    )}
                </div>
                <div ref={messagesEndRef} data-attr="messages-end" />
            </div>

            {/* Output area */}
            <OutputSection />
        </>
    )
}

function SystemMessageDisplay({ expandTextAreas }: { expandTextAreas: boolean }): JSX.Element {
    const { systemPrompt } = useValues(llmObservabilityPlaygroundLogic)
    const { setSystemPrompt } = useActions(llmObservabilityPlaygroundLogic)
    const [showEditModal, setShowEditModal] = useState(false)

    return (
        <>
            <div className="border rounded p-3 relative group bg-white dark:bg-[var(--color-card)] border-l-4 border-l-[var(--color-purple-500)]">
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit system prompt"
                        noPadding
                        onClick={() => setShowEditModal(true)}
                    />
                </div>

                <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-medium px-2 py-1 rounded">System</span>
                </div>

                <LemonTextArea
                    className="text-sm w-full"
                    placeholder="System instructions for the AI assistant..."
                    value={systemPrompt}
                    onChange={setSystemPrompt}
                    minRows={2}
                    maxRows={expandTextAreas ? undefined : 4}
                />
            </div>

            <LemonModal
                isOpen={showEditModal}
                onClose={() => setShowEditModal(false)}
                title="Edit System Prompt"
                width="90vw"
                maxWidth="1200px"
            >
                <div className="space-y-4">
                    <div>
                        <label className="font-semibold mb-1 block text-sm">System Instructions</label>
                        <LemonTextArea
                            className="text-sm w-full"
                            placeholder="System instructions for the AI assistant..."
                            value={systemPrompt}
                            onChange={setSystemPrompt}
                            minRows={8}
                        />
                    </div>
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={() => setShowEditModal(false)}>
                            Close
                        </LemonButton>
                    </div>
                </div>
            </LemonModal>
        </>
    )
}

function MessageDisplay({
    message,
    index,
    expandTextAreas,
}: {
    message: Message
    index: number
    expandTextAreas: boolean
}): JSX.Element {
    const { updateMessage, deleteMessage } = useActions(llmObservabilityPlaygroundLogic)
    const [showEditModal, setShowEditModal] = useState(false)

    const longMessageThreshold = 300
    const isLongMessage = message.content.length > longMessageThreshold

    const handleRoleChange = (newRole: MessageRole): void => {
        updateMessage(index, { role: newRole })
    }

    const handleContentChange = (newContent: string): void => {
        updateMessage(index, { content: newContent })
    }

    const roleOptions: { label: string; value: MessageRole }[] = [
        { label: 'User', value: 'user' },
        { label: 'Assistant', value: 'assistant' },
        { label: 'System', value: 'system' },
    ]

    const getRoleBorderClass = (role: MessageRole): string => {
        switch (role) {
            case 'user':
                return 'border-l-4 border-l-[var(--color-blue-500)]'
            case 'assistant':
                return 'border-l-4 border-l-[var(--color-green-500)]'
            case 'system':
                return 'border-l-4 border-l-[var(--color-purple-500)]'
            default:
                return ''
        }
    }

    return (
        <>
            <div
                className={`border rounded p-3 relative group bg-white dark:bg-[var(--color-card)] hover:shadow-sm transition-shadow ${getRoleBorderClass(
                    message.role
                )}`}
            >
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit in large modal"
                        noPadding
                        onClick={() => setShowEditModal(true)}
                    />
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
                    maxRows={expandTextAreas ? undefined : isLongMessage ? 2 : 4}
                />
            </div>

            {/* Edit modal for long messages */}
            <LemonModal
                isOpen={showEditModal}
                onClose={() => setShowEditModal(false)}
                title="Edit Message"
                width="max(44vw)"
            >
                <div className="space-y-4">
                    <div>
                        <label className="font-semibold mb-1 block text-sm">Role</label>
                        <LemonSelect<MessageRole>
                            options={roleOptions}
                            value={message.role}
                            onChange={handleRoleChange}
                            dropdownMatchSelectWidth={false}
                        />
                    </div>
                    <div>
                        <label className="font-semibold mb-1 block text-sm">Content</label>
                        <LemonTextArea
                            className="text-sm w-full"
                            placeholder={`Enter ${message.role} message here...`}
                            value={message.content}
                            onChange={handleContentChange}
                            minRows={12}
                        />
                    </div>
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={() => setShowEditModal(false)}>
                            Close
                        </LemonButton>
                    </div>
                </div>
            </LemonModal>
        </>
    )
}

function OutputSection(): JSX.Element {
    const { submitting, currentResponse, lastRunDetails, responseHasError } = useValues(llmObservabilityPlaygroundLogic)
    const { addResponseToHistory, addCurrentRunToComparison } = useActions(llmObservabilityPlaygroundLogic)

    return (
        <div className="p-4">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold">AI Response</h3>
                <div className="flex gap-2">
                    {!submitting && currentResponse && currentResponse.trim() && !responseHasError && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => addResponseToHistory(currentResponse)}
                        >
                            Add to Chat History
                        </LemonButton>
                    )}
                    {!submitting && lastRunDetails && !responseHasError && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={addCurrentRunToComparison}
                            tooltip="Add this run to comparison table"
                        >
                            Add to Compare
                        </LemonButton>
                    )}
                </div>
            </div>

            <div
                className={`border rounded p-4 min-h-32 ${
                    responseHasError
                        ? 'bg-red-50 dark:bg-red-900/20 border-red-300 dark:border-red-800'
                        : 'bg-bg-light dark:bg-[var(--color-card)]'
                }`}
            >
                {submitting && (currentResponse === null || currentResponse === '') && (
                    <LemonSkeleton active className="my-2" />
                )}
                {currentResponse ? (
                    <pre
                        className={`whitespace-pre-wrap text-sm break-words ${
                            responseHasError ? 'text-red-800 dark:text-red-200' : ''
                        }`}
                    >
                        {currentResponse}
                        {submitting && <span className="text-tertiary-foreground italic"> (streaming...)</span>}
                    </pre>
                ) : (
                    <div className="flex items-center justify-center h-24 text-tertiary-foreground">
                        <p>AI response will appear here after running your prompt</p>
                    </div>
                )}
            </div>
        </div>
    )
}

function ConfigurationPanel(): JSX.Element {
    const { temperature, maxTokens, thinking, model, modelOptions, modelOptionsLoading } = useValues(
        llmObservabilityPlaygroundLogic
    )
    const { setTemperature, setMaxTokens, setThinking, setModel } = useActions(llmObservabilityPlaygroundLogic)

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
                    <div className="text-xs text-tertiary-foreground mt-1 flex justify-between">
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
                    className="rounded text-foreground focus:ring-primary"
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
                <div className="max-h-40 overflow-y-auto whitespace-pre-wrap text-xs break-words p-1 border rounded bg-bg-light dark:bg-[var(--color-card)]">
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
            <div className="flex-1 overflow-hidden">
                <LemonTable dataSource={comparisonItems} columns={columns} rowKey="id" loading={false} embedded />
            </div>
        </div>
    )
}

function StickyActionBar(): JSX.Element {
    const { messages, submitting, model, temperature, maxTokens } = useValues(llmObservabilityPlaygroundLogic)
    const { addMessage, clearConversation, submitPrompt } = useActions(llmObservabilityPlaygroundLogic)
    const [showConfigModal, setShowConfigModal] = useState(false)

    const scrollToTop = (): void => {
        const element = document.querySelector('[data-attr="llm-observability-tabs"]') as HTMLElement
        element?.scrollIntoView({ behavior: 'smooth' })
    }

    const scrollToBottom = (): void => {
        const element = document.querySelector('[data-attr="messages-end"]') as HTMLElement
        element?.scrollIntoView({ behavior: 'smooth' })
    }

    let runDisabledReason = undefined
    if (messages.length === 0) {
        runDisabledReason = 'Add messages to start the conversation'
    }

    return (
        <>
            <div className="sticky bottom-0 bg-bg-light dark:bg-[var(--color-card)] border-t border-border z-10 ml-[calc(var(--scene-padding)*-1)] mr-[calc(var(--scene-padding)*-1)] mb-[calc(var(--scene-padding-bottom)*-1)]">
                <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
                    <div className="flex gap-2 items-center">
                        <LemonButton
                            type="secondary"
                            icon={<IconPlus />}
                            onClick={() => {
                                addMessage()
                                scrollToBottom()
                            }}
                            disabled={submitting}
                        >
                            Add Message
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={clearConversation}
                            disabled={submitting || messages.length === 0}
                            tooltip="Clear all messages"
                        >
                            Clear All
                        </LemonButton>
                        {messages.length > 3 && (
                            <>
                                <div className="border-l border-border mx-2 h-6" />
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    icon={<IconArrowUp />}
                                    onClick={scrollToTop}
                                    tooltip="Jump to top"
                                />
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    icon={<IconArrowDown />}
                                    onClick={scrollToBottom}
                                    tooltip="Jump to bottom"
                                />
                            </>
                        )}
                    </div>

                    <div className="flex items-center gap-3">
                        {/* Model and params summary */}
                        <div className="flex items-center gap-2 text-xs text-tertiary-foreground bg-bg-dark dark:bg-bg-light px-2 py-1 rounded">
                            <span className="font-medium">{model || 'No model'}</span>
                            <span>•</span>
                            <span>T:{temperature}</span>
                            <span>•</span>
                            <span>Max:{maxTokens}</span>
                        </div>

                        <LemonButton
                            type="secondary"
                            icon={<IconGear />}
                            onClick={() => setShowConfigModal(true)}
                            tooltip="Model settings"
                            size="small"
                        >
                            Settings
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            icon={<IconPlay />}
                            onClick={submitPrompt}
                            loading={submitting}
                            disabledReason={submitting ? 'Generating...' : runDisabledReason}
                        >
                            Run
                        </LemonButton>
                    </div>
                </div>
            </div>

            <LemonModal
                isOpen={showConfigModal}
                onClose={() => setShowConfigModal(false)}
                title="Model Configuration"
                width="large"
            >
                <ConfigurationPanel />
                <div className="flex justify-end gap-2 mt-4">
                    <LemonButton type="secondary" onClick={() => setShowConfigModal(false)}>
                        Close
                    </LemonButton>
                </div>
            </LemonModal>
        </>
    )
}
