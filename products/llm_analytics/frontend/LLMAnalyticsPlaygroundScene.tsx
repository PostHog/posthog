import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import {
    IconChevronDown,
    IconChevronRight,
    IconCopy,
    IconGear,
    IconMessage,
    IconPencil,
    IconPlay,
    IconPlus,
    IconTrash,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyDuration } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SceneExport } from 'scenes/sceneTypes'

import { llmAnalyticsPlaygroundLogic } from './llmAnalyticsPlaygroundLogic'
import { ComparisonItem, Message, MessageRole, ModelOption } from './llmAnalyticsPlaygroundLogic'
import { formatTokens } from './utils'

const formatMs = (ms: number | null | undefined): string => {
    if (ms === null || typeof ms === 'undefined') {
        return '-'
    }
    if (ms < 1000) {
        return `${ms.toFixed(0)} ms`
    }
    return `${(ms / 1000).toFixed(2)} s`
}

function scrollToOutput(): void {
    setTimeout(() => {
        document.querySelector('[data-attr="output-section"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 100)
}

export const scene: SceneExport = {
    component: LLMAnalyticsPlaygroundScene,
    logic: llmAnalyticsPlaygroundLogic,
}

export function LLMAnalyticsPlaygroundScene(): JSX.Element {
    return (
        <BindLogic logic={llmAnalyticsPlaygroundLogic} props={{ key: 'llm-analytics-playground-scene' }}>
            <PlaygroundLayout />
        </BindLogic>
    )
}

function RateLimitBanner(): JSX.Element | null {
    const { rateLimitedUntil } = useValues(llmAnalyticsPlaygroundLogic)

    if (rateLimitedUntil === null || Date.now() >= rateLimitedUntil) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mb-4">
            You've hit our playground request limit. You can make another request in{' '}
            <strong>{humanFriendlyDuration(Math.ceil((rateLimitedUntil - Date.now()) / 1000), { maxUnits: 1 })}</strong>
            . We're working on bring-your-own-key and other improvements to remove this limit.
        </LemonBanner>
    )
}

function SubscriptionRequiredBanner(): JSX.Element | null {
    const { subscriptionRequired } = useValues(llmAnalyticsPlaygroundLogic)

    if (!subscriptionRequired) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mb-4">
            The playground requires a{' '}
            <Link to="/organization/billing" className="font-semibold">
                valid payment method
            </Link>{' '}
            on file to prevent abuse.
        </LemonBanner>
    )
}

function PlaygroundLayout(): JSX.Element {
    const { submitting, currentResponse, responseHasError } = useValues(llmAnalyticsPlaygroundLogic)
    const { addResponseToHistory, addMessage } = useActions(llmAnalyticsPlaygroundLogic)
    const prevSubmittingRef = useRef(false)

    useEffect(() => {
        const wasSubmitting = prevSubmittingRef.current
        prevSubmittingRef.current = submitting

        if (wasSubmitting && !submitting && currentResponse && currentResponse.trim() && !responseHasError) {
            addResponseToHistory(currentResponse)
            addMessage()
            setTimeout(() => {
                document.querySelector('[data-attr="messages-end"]')?.scrollIntoView({ behavior: 'smooth' })
            }, 150)
        }
    }, [submitting])

    return (
        <div className="flex flex-col min-h-[calc(100vh-120px)] relative">
            <RateLimitBanner />
            <SubscriptionRequiredBanner />

            <ModelConfigBar />

            <MessagesSection />
            <LemonDivider label="Response" className="my-4" />
            <OutputSection />

            <ComparisonTablePanel />
            <StickyActionBar />
        </div>
    )
}

function getModelOptionsErrorMessage(errorStatus: number | null): string | null {
    if (errorStatus === null) {
        return null
    }
    if (errorStatus === 429) {
        return 'Too many requests. Please wait a moment and try again.'
    }
    return 'Failed to load models. Please refresh the page or try again later.'
}

function ModelConfigBar(): JSX.Element {
    const {
        model,
        maxTokens,
        thinking,
        reasoningLevel,
        modelOptions,
        modelOptionsLoading,
        modelOptionsErrorStatus,
        tools,
    } = useValues(llmAnalyticsPlaygroundLogic)
    const { setModel, setMaxTokens, setThinking, setReasoningLevel, loadModelOptions, setTools } =
        useActions(llmAnalyticsPlaygroundLogic)
    const [showSettings, setShowSettings] = useState(false)

    const options = Array.isArray(modelOptions) ? modelOptions : []
    const errorMessage = getModelOptionsErrorMessage(modelOptionsErrorStatus)
    const hasNonDefaultSettings = maxTokens !== null || thinking || reasoningLevel !== null

    return (
        <div className="mb-4 space-y-3">
            <div className="flex items-center gap-3">
                <div className="flex-1 max-w-sm">
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
                            disabledReason={
                                modelOptionsLoading
                                    ? 'Loading models...'
                                    : options.length === 0
                                      ? 'No models available'
                                      : undefined
                            }
                            data-attr="playground-model-selector"
                        />
                    )}
                    {options.length === 0 && !modelOptionsLoading && (
                        <div className="mt-1">
                            <p className="text-xs text-danger">{errorMessage || 'No models available.'}</p>
                            <button
                                type="button"
                                className="text-xs text-link mt-1 underline"
                                onClick={() => loadModelOptions()}
                            >
                                Retry
                            </button>
                        </div>
                    )}
                </div>

                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconGear />}
                    onClick={() => setShowSettings(!showSettings)}
                    active={showSettings || hasNonDefaultSettings}
                    tooltip="Max tokens, thinking, reasoning"
                >
                    Settings
                    {hasNonDefaultSettings && !showSettings && (
                        <span className="ml-1 w-1.5 h-1.5 rounded-full bg-primary inline-block" />
                    )}
                </LemonButton>

                {!tools && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={() => setTools([])}
                        tooltip="Add tools block"
                    >
                        Add tools
                    </LemonButton>
                )}
            </div>

            {showSettings && (
                <div className="flex items-end gap-4 p-3 border rounded bg-bg-light">
                    <div className="max-w-[180px]">
                        <label className="text-xs font-medium mb-1 block">Max tokens</label>
                        <LemonInput
                            type="number"
                            value={maxTokens ?? undefined}
                            onChange={(val) => setMaxTokens(val ?? null)}
                            min={1}
                            max={16384}
                            step={64}
                            placeholder="Model default"
                            size="small"
                        />
                    </div>

                    <LemonSwitch
                        bordered
                        checked={thinking}
                        onChange={setThinking}
                        label="Thinking"
                        size="small"
                        tooltip="Enable thinking/reasoning stream (if supported)"
                    />

                    <div className="max-w-[140px]">
                        <label className="text-xs font-medium mb-1 block">Reasoning</label>
                        <LemonSelect<'minimal' | 'low' | 'medium' | 'high' | null>
                            size="small"
                            placeholder="None"
                            value={reasoningLevel}
                            onChange={(value) => setReasoningLevel(value ?? null)}
                            options={[
                                { label: 'None', value: null },
                                { label: 'Minimal', value: 'minimal' },
                                { label: 'Low', value: 'low' },
                                { label: 'Medium', value: 'medium' },
                                { label: 'High', value: 'high' },
                            ]}
                            dropdownMatchSelectWidth={false}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}

function MessagesSection(): JSX.Element {
    const { messages, tools } = useValues(llmAnalyticsPlaygroundLogic)
    const [expandTextAreas, setExpandTextAreas] = useState(false)

    return (
        <div>
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">Messages</h3>
                <LemonSwitch
                    bordered
                    checked={expandTextAreas}
                    onChange={setExpandTextAreas}
                    label="Expand"
                    size="small"
                    tooltip="Expand all text areas to show full content"
                />
            </div>

            <div className="space-y-3">
                <SystemMessageDisplay expandTextAreas={expandTextAreas} />
                {tools && <ToolsDisplay expandTextAreas={expandTextAreas} />}
                {messages.map((message, index) => (
                    <MessageDisplay key={index} index={index} message={message} expandTextAreas={expandTextAreas} />
                ))}
                {messages.length === 0 && <EmptyMessagesState />}
            </div>

            <div data-attr="messages-end" />
        </div>
    )
}

function EmptyMessagesState(): JSX.Element {
    const { addMessage } = useActions(llmAnalyticsPlaygroundLogic)

    return (
        <div className="flex flex-col items-center justify-center py-16 text-muted border border-dashed rounded">
            <IconMessage className="text-4xl mb-2 opacity-40" />
            <p className="mb-1">No messages yet</p>
            <p className="text-xs opacity-60 mb-4">Add a message to start building your prompt</p>
            <LemonButton type="secondary" icon={<IconPlus />} onClick={() => addMessage()}>
                Add your first message
            </LemonButton>
        </div>
    )
}

function ToolsDisplay({ expandTextAreas }: { expandTextAreas: boolean }): JSX.Element {
    const { tools } = useValues(llmAnalyticsPlaygroundLogic)
    const { setTools, submitPrompt } = useActions(llmAnalyticsPlaygroundLogic)
    const [showEditModal, setShowEditModal] = useState(false)
    const [localToolsJson, setLocalToolsJson] = useState<string | null>(null)
    const [collapsed, setCollapsed] = useState(false)

    if (!tools) {
        return <></>
    }

    const toolsJsonString = localToolsJson ?? JSON.stringify(tools, null, 2)
    const toolCount = Array.isArray(tools) ? tools.length : 0

    const handleToolsChange = (value: string): void => {
        setLocalToolsJson(value)
        try {
            const parsedTools = JSON.parse(value)
            setTools(parsedTools)
        } catch {
            // Not valid JSON yet, keep local state for display
        }
    }

    return (
        <>
            <div className="border rounded p-3 relative group bg-surface-secondary border-l-4 border-l-[var(--color-orange-500)]">
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit tools in modal"
                        noPadding
                        onClick={() => setShowEditModal(true)}
                    />
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Remove tools block"
                        noPadding
                        onClick={() => setTools(null)}
                    />
                </div>

                <div className="flex items-center gap-2 mb-2 cursor-pointer" onClick={() => setCollapsed(!collapsed)}>
                    <LemonButton
                        size="xsmall"
                        icon={collapsed ? <IconChevronRight /> : <IconChevronDown />}
                        noPadding
                    />
                    <LemonTag type="caution" size="small">
                        Tools
                    </LemonTag>
                    {collapsed && (
                        <span className="text-xs text-muted truncate flex-1">
                            {toolCount > 0 ? `${toolCount} tool${toolCount === 1 ? '' : 's'} defined` : 'No tools'}
                        </span>
                    )}
                </div>

                <AnimatedCollapsible collapsed={collapsed}>
                    <LemonTextArea
                        className="text-sm w-full font-mono"
                        placeholder="Tools available to the AI assistant (JSON format)..."
                        value={toolsJsonString}
                        onChange={handleToolsChange}
                        minRows={2}
                        maxRows={expandTextAreas ? undefined : 6}
                        onPressCmdEnter={() => {
                            submitPrompt()
                            scrollToOutput()
                        }}
                    />
                </AnimatedCollapsible>
            </div>

            <LemonModal
                isOpen={showEditModal}
                onClose={() => setShowEditModal(false)}
                title="Edit tools"
                width="90vw"
                maxWidth="1200px"
            >
                <div className="space-y-4">
                    <div>
                        <label className="font-semibold mb-1 block text-sm">Tools (JSON)</label>
                        <LemonTextArea
                            className="text-sm w-full font-mono"
                            placeholder="Tools available to the AI assistant (JSON format)..."
                            value={toolsJsonString}
                            onChange={handleToolsChange}
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

function SystemMessageDisplay({ expandTextAreas }: { expandTextAreas: boolean }): JSX.Element {
    const { systemPrompt } = useValues(llmAnalyticsPlaygroundLogic)
    const { setSystemPrompt, submitPrompt } = useActions(llmAnalyticsPlaygroundLogic)
    const [showEditModal, setShowEditModal] = useState(false)
    const [collapsed, setCollapsed] = useState(false)

    return (
        <>
            <div className="border rounded p-3 relative group bg-surface-secondary border-l-4 border-l-[var(--color-purple-500)]">
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit system prompt in modal"
                        noPadding
                        onClick={() => setShowEditModal(true)}
                    />
                </div>

                <div className="flex items-center gap-2 mb-2 cursor-pointer" onClick={() => setCollapsed(!collapsed)}>
                    <LemonButton
                        size="xsmall"
                        icon={collapsed ? <IconChevronRight /> : <IconChevronDown />}
                        noPadding
                    />
                    <LemonTag type="completion" size="small">
                        System
                    </LemonTag>
                    {collapsed && (
                        <span className="text-xs text-muted truncate flex-1">
                            {systemPrompt
                                ? systemPrompt.slice(0, 80) + (systemPrompt.length > 80 ? '…' : '')
                                : 'No system prompt'}
                        </span>
                    )}
                </div>

                <AnimatedCollapsible collapsed={collapsed}>
                    <LemonTextArea
                        className="text-sm w-full"
                        placeholder="System instructions for the AI assistant..."
                        value={systemPrompt}
                        onChange={setSystemPrompt}
                        minRows={2}
                        maxRows={expandTextAreas ? undefined : 8}
                        onPressCmdEnter={() => {
                            submitPrompt()
                            scrollToOutput()
                        }}
                    />
                </AnimatedCollapsible>
            </div>

            <LemonModal
                isOpen={showEditModal}
                onClose={() => setShowEditModal(false)}
                title="Edit system prompt"
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
    const { updateMessage, deleteMessage, submitPrompt } = useActions(llmAnalyticsPlaygroundLogic)

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

    const getRoleDotClass = (role: MessageRole): string => {
        switch (role) {
            case 'user':
                return 'bg-[var(--color-blue-500)]'
            case 'assistant':
                return 'bg-[var(--color-green-500)]'
            case 'system':
                return 'bg-[var(--color-purple-500)]'
            default:
                return 'bg-muted'
        }
    }

    const isAssistantWithContent = message.role === 'assistant' && message.content.trim().length > 0

    return (
        <div
            className={`border rounded p-3 relative group hover:shadow-sm transition-shadow ${getRoleBorderClass(
                message.role
            )} ${isAssistantWithContent ? 'bg-surface-secondary' : 'bg-white dark:bg-[var(--color-bg-surface-primary)]'}`}
        >
            <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
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
                <span className={`w-2 h-2 rounded-full shrink-0 ${getRoleDotClass(message.role)}`} />
                <LemonSelect<MessageRole>
                    size="small"
                    options={roleOptions}
                    value={message.role}
                    onChange={handleRoleChange}
                    dropdownMatchSelectWidth={false}
                />
            </div>

            {isAssistantWithContent ? (
                <div className="text-sm opacity-75">
                    <LemonMarkdown className="break-words" lowKeyHeadings wrapCode>
                        {message.content}
                    </LemonMarkdown>
                </div>
            ) : (
                <LemonTextArea
                    className="text-sm w-full"
                    placeholder={`Enter ${message.role} message here...`}
                    value={message.content}
                    onChange={handleContentChange}
                    minRows={2}
                    maxRows={expandTextAreas ? undefined : 8}
                    onPressCmdEnter={() => {
                        submitPrompt()
                        scrollToOutput()
                    }}
                />
            )}
        </div>
    )
}

function OutputSection(): JSX.Element {
    const { submitting, currentResponse, lastRunDetails, responseHasError } = useValues(llmAnalyticsPlaygroundLogic)
    const { addCurrentRunToComparison } = useActions(llmAnalyticsPlaygroundLogic)

    return (
        <div data-attr="output-section">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold">Response</h3>
                <div className="flex gap-2">
                    {!submitting && currentResponse && currentResponse.trim() && !responseHasError && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconCopy />}
                            onClick={() => void copyToClipboard(currentResponse, 'response')}
                            tooltip="Copy response"
                        />
                    )}
                    {!submitting && lastRunDetails && !responseHasError && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={addCurrentRunToComparison}
                            tooltip="Add this run to comparison table"
                            data-attr="playground-add-to-compare"
                        >
                            Add to compare
                        </LemonButton>
                    )}
                </div>
            </div>

            <div
                className={`relative border rounded p-4 min-h-32 bg-white dark:bg-[var(--color-bg-surface-primary)] ${
                    responseHasError ? 'border-red-300 dark:border-red-800' : ''
                }`}
            >
                {submitting && (
                    <div className="absolute top-0 left-0 right-0 h-0.5 bg-primary animate-pulse rounded-t" />
                )}
                {submitting && (currentResponse === null || currentResponse === '') && (
                    <LemonSkeleton active className="my-2" />
                )}
                {currentResponse !== null ? (
                    responseHasError ? (
                        <pre className="whitespace-pre-wrap text-sm break-words text-red-800 dark:text-red-200">
                            {currentResponse}
                        </pre>
                    ) : (
                        <LemonMarkdown className="text-sm break-words" lowKeyHeadings wrapCode>
                            {currentResponse}
                        </LemonMarkdown>
                    )
                ) : (
                    <div className="flex flex-col items-center justify-center h-24 text-muted">
                        <IconMessage className="text-3xl mb-2 opacity-40" />
                        <p>Run your prompt to see the response</p>
                        <p className="text-xs opacity-60">Press Cmd+Enter from any message</p>
                    </div>
                )}
            </div>

            {!submitting && lastRunDetails && !responseHasError && (
                <div className="flex items-center gap-3 mt-2 text-xs text-muted">
                    <LemonTag type="muted" size="small">
                        {lastRunDetails.model}
                    </LemonTag>
                    {lastRunDetails.usage?.prompt_tokens != null && (
                        <span>{formatTokens(lastRunDetails.usage.prompt_tokens)} in</span>
                    )}
                    {lastRunDetails.usage?.completion_tokens != null && (
                        <span>{formatTokens(lastRunDetails.usage.completion_tokens)} out</span>
                    )}
                    {lastRunDetails.ttftMs != null && <span>TTFT {formatMs(lastRunDetails.ttftMs)}</span>}
                    {lastRunDetails.latencyMs != null && <span>Total {formatMs(lastRunDetails.latencyMs)}</span>}
                </div>
            )}
        </div>
    )
}

function ComparisonTablePanel(): JSX.Element {
    const { comparisonItems } = useValues(llmAnalyticsPlaygroundLogic)
    const { clearComparison } = useActions(llmAnalyticsPlaygroundLogic)

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
                <div className="max-h-40 overflow-y-auto whitespace-pre-wrap text-xs break-words p-1 border rounded bg-bg-light dark:bg-[var(--color-bg-surface-primary)]">
                    {typeof response === 'string' && response ? (
                        response
                    ) : (
                        <span className="text-muted italic">No response</span>
                    )}
                </div>
            ),
            width: '35%',
        },
        {
            title: 'In tokens',
            dataIndex: 'usage',
            render: (_, item) => (item.usage?.prompt_tokens != null ? formatTokens(item.usage.prompt_tokens) : '-'),
            align: 'right' as const,
            tooltip: 'Input/prompt tokens',
        },
        {
            title: 'Out tokens',
            dataIndex: 'usage',
            render: (_, item) =>
                item.usage?.completion_tokens != null ? formatTokens(item.usage.completion_tokens) : '-',
            align: 'right' as const,
            tooltip: 'Output/completion tokens',
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
        return <></>
    }

    return (
        <div className="border rounded p-4 min-h-0 flex flex-col mt-4">
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
                    Clear all
                </LemonButton>
            </div>
            <div className="flex-1 overflow-hidden">
                <LemonTable dataSource={comparisonItems} columns={columns} rowKey="id" loading={false} embedded />
            </div>
        </div>
    )
}

function StickyActionBar(): JSX.Element {
    const { messages, submitting } = useValues(llmAnalyticsPlaygroundLogic)
    const { addMessage, clearConversation, submitPrompt } = useActions(llmAnalyticsPlaygroundLogic)

    const scrollToBottom = (): void => {
        const element = document.querySelector('[data-attr="messages-end"]') as HTMLElement
        element?.scrollIntoView({ behavior: 'smooth' })
    }

    return (
        <div className="sticky bottom-0 bg-bg-light dark:bg-[var(--color-bg-surface-primary)] border-t border-border z-10 ml-[calc(var(--scene-padding)*-1)] mr-[calc(var(--scene-padding)*-1)] mb-[calc(var(--scene-padding-bottom)*-1)]">
            <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
                <div className="flex gap-2 items-center">
                    <LemonButton
                        type="secondary"
                        icon={<IconPlus />}
                        onClick={() => {
                            addMessage()
                            scrollToBottom()
                        }}
                        disabledReason={submitting ? 'Generating...' : undefined}
                        data-attr="ai-playground-run-button"
                    >
                        Add message
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={clearConversation}
                        disabledReason={
                            messages.length === 0 ? 'No messages to clear' : submitting ? 'Generating...' : undefined
                        }
                        tooltip="Clear all messages"
                    >
                        Clear all
                    </LemonButton>
                </div>

                <LemonButton
                    type="primary"
                    icon={<IconPlay />}
                    onClick={() => {
                        submitPrompt()
                        scrollToOutput()
                    }}
                    loading={submitting}
                    tooltip="Run prompt (⌘↵)"
                    disabledReason={
                        submitting
                            ? 'Generating...'
                            : messages.length === 0
                              ? 'Add messages to start the conversation'
                              : undefined
                    }
                    data-attr="playground-run"
                >
                    Run
                </LemonButton>
            </div>
        </div>
    )
}
