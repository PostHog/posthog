import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import {
    IconChevronDown,
    IconChevronRight,
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
    LemonDropdown,
    LemonInput,
    LemonModal,
    LemonSearchableSelect,
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
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ByokModelPicker } from './ByokModelPicker'
import { JSONEditor } from './components/JSONEditor'
import { llmAnalyticsPlaygroundLogic } from './llmAnalyticsPlaygroundLogic'
import { ComparisonItem, Message, MessageRole } from './llmAnalyticsPlaygroundLogic'
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

export const scene: SceneExport = {
    component: LLMAnalyticsPlaygroundScene,
    logic: llmAnalyticsPlaygroundLogic,
    productKey: ProductKey.LLM_ANALYTICS,
}

export function LLMAnalyticsPlaygroundScene(): JSX.Element {
    useMountedLogic(llmAnalyticsPlaygroundLogic)
    const { messages, submitting } = useValues(llmAnalyticsPlaygroundLogic)
    const { submitPrompt } = useActions(llmAnalyticsPlaygroundLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Playground"
                description="Test and experiment with LLM prompts in a sandbox environment."
                resourceType={{ type: 'llm_playground' }}
                actions={
                    <LemonButton
                        type="primary"
                        icon={<IconPlay />}
                        onClick={() => submitPrompt()}
                        loading={submitting}
                        tooltip="Run prompt (⌘↵)"
                        disabledReason={
                            submitting
                                ? 'Generating...'
                                : messages.length === 0
                                  ? 'Add messages to start the conversation'
                                  : undefined
                        }
                        size="small"
                        data-attr="playground-run"
                    >
                        Run
                    </LemonButton>
                }
            />
            <PlaygroundLayout />
        </SceneContent>
    )
}

function RateLimitBanner(): JSX.Element | null {
    const { rateLimitedUntil } = useValues(llmAnalyticsPlaygroundLogic)

    if (rateLimitedUntil === null || Date.now() >= rateLimitedUntil) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mb-4">
            You've hit the playground request limit for shared keys. You can make another request in{' '}
            <strong>{humanFriendlyDuration(Math.ceil((rateLimitedUntil - Date.now()) / 1000), { maxUnits: 1 })}</strong>
            .
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
    return (
        <div className="flex flex-col gap-4 pb-6">
            <RateLimitBanner />
            <SubscriptionRequiredBanner />

            <section className="border rounded overflow-hidden min-h-0 flex flex-col max-h-[55vh] lg:max-h-[60vh]">
                <div className="p-4 space-y-4 min-h-0 overflow-y-auto">
                    <ModelConfigBar />
                    <MessagesSection />
                </div>
            </section>

            <ResultsSection />
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

function ModelPicker(): JSX.Element {
    const {
        model,
        effectiveModelOptions,
        selectedProviderKeyId,
        hasByokKeys,
        modelOptions,
        modelOptionsLoading,
        modelOptionsErrorStatus,
        groupedModelOptions,
    } = useValues(llmAnalyticsPlaygroundLogic)
    const { setModel, loadModelOptions } = useActions(llmAnalyticsPlaygroundLogic)

    if (hasByokKeys) {
        const options = Array.isArray(effectiveModelOptions) ? effectiveModelOptions : []
        const selectedModel = options.find((m) => m.id === model)

        return (
            <ByokModelPicker
                model={model}
                selectedProviderKeyId={selectedProviderKeyId}
                onSelect={(modelId, providerKeyId) => setModel(modelId, providerKeyId)}
                selectedModelName={selectedModel?.name}
                data-attr="playground-model-selector"
            />
        )
    }

    const options = Array.isArray(modelOptions) ? modelOptions : []
    const errorMessage = getModelOptionsErrorMessage(modelOptionsErrorStatus)

    return (
        <>
            {modelOptionsLoading && !options.length ? (
                <LemonSkeleton className="h-10" />
            ) : (
                <LemonSearchableSelect
                    className="w-full"
                    placeholder="Select model"
                    value={model}
                    onChange={(value) => value && setModel(value)}
                    options={groupedModelOptions}
                    searchPlaceholder="Search models..."
                    searchKeys={['label', 'value', 'tooltip']}
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
        </>
    )
}

function SettingsDropdownOverlay(): JSX.Element {
    const { maxTokens, thinking, reasoningLevel } = useValues(llmAnalyticsPlaygroundLogic)
    const { setMaxTokens, setThinking, setReasoningLevel } = useActions(llmAnalyticsPlaygroundLogic)

    return (
        <div className="space-y-3 p-3 w-[280px]">
            <div>
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

            <div>
                <label className="text-xs font-medium mb-1 block">Reasoning effort</label>
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
                    fullWidth
                    dropdownMatchSelectWidth={false}
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
        </div>
    )
}

function ModelConfigBar(): JSX.Element {
    const { maxTokens, thinking, reasoningLevel } = useValues(llmAnalyticsPlaygroundLogic)

    const hasNonDefaultSettings = maxTokens !== null || thinking || reasoningLevel !== 'medium'

    return (
        <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1 min-w-[260px] max-w-lg">
                <ModelPicker />
            </div>

            <LemonDropdown overlay={<SettingsDropdownOverlay />} closeOnClickInside={false} placement="bottom-end">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconGear />}
                    tooltip="Max tokens, thinking, reasoning"
                    active={hasNonDefaultSettings}
                >
                    Settings
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}

function MessagesSection(): JSX.Element {
    const { messages, tools, submitting } = useValues(llmAnalyticsPlaygroundLogic)
    const { addMessage, setTools } = useActions(llmAnalyticsPlaygroundLogic)

    return (
        <div className="space-y-3">
            <SystemMessageDisplay />
            {tools && <ToolsDisplay />}
            {messages.map((message, index) => (
                <MessageDisplay key={index} index={index} message={message} />
            ))}
            <div className="flex items-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => addMessage()}
                    disabledReason={submitting ? 'Generating...' : undefined}
                >
                    Message
                </LemonButton>
                {!tools && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={() => setTools([])}
                        disabledReason={submitting ? 'Generating...' : undefined}
                    >
                        Tools
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

function ToolsDisplay(): JSX.Element {
    const { tools } = useValues(llmAnalyticsPlaygroundLogic)
    const { setTools, submitPrompt } = useActions(llmAnalyticsPlaygroundLogic)
    const [showEditModal, setShowEditModal] = useState(false)
    const [localToolsJson, setLocalToolsJson] = useState<string | null>(null)
    const [collapsed, setCollapsed] = useState(false)

    if (!tools) {
        return null
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
                    <div className="border rounded">
                        <JSONEditor
                            value={toolsJsonString}
                            onChange={handleToolsChange}
                            defaultNumberOfLines={2}
                            maxNumberOfLines={60}
                            onPressCmdEnter={() => submitPrompt()}
                        />
                    </div>
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
                        <div className="border rounded">
                            <JSONEditor
                                value={toolsJsonString}
                                onChange={handleToolsChange}
                                defaultNumberOfLines={12}
                                maxNumberOfLines={40}
                                autoFocus
                            />
                        </div>
                        <div className="mt-2 text-xs text-muted">Paste or edit valid JSON tool definitions.</div>
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

function SystemMessageDisplay(): JSX.Element {
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
                        maxRows={undefined}
                        onPressCmdEnter={() => submitPrompt()}
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

function MessageDisplay({ message, index }: { message: Message; index: number }): JSX.Element {
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

    return (
        <div
            className={`border rounded p-3 relative group hover:shadow-sm transition-shadow ${getRoleBorderClass(
                message.role
            )}`}
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

            <LemonTextArea
                className="text-sm w-full"
                placeholder={`Enter ${message.role} message here...`}
                value={message.content}
                onChange={handleContentChange}
                minRows={2}
                maxRows={undefined}
                onPressCmdEnter={() => submitPrompt()}
            />
        </div>
    )
}

function ResultsSection(): JSX.Element {
    const { submitting, displayItems } = useValues(llmAnalyticsPlaygroundLogic)

    const columns: LemonTableColumns<ComparisonItem> = [
        {
            title: 'Model',
            dataIndex: 'model',
            render: (model, item) => (
                <LemonTag type={item.error ? 'danger' : 'default'}>
                    {typeof model === 'string' ? model || '-' : '-'}
                </LemonTag>
            ),
            sorter: (a, b) => a.model.localeCompare(b.model),
        },
        {
            title: 'Response',
            dataIndex: 'response',
            render: (response, item) => (
                <div className={`max-h-40 overflow-y-auto text-xs break-words p-1 ${item.error ? 'text-danger' : ''}`}>
                    {typeof response === 'string' && response ? (
                        <LemonMarkdown className="break-words" lowKeyHeadings wrapCode>
                            {response}
                        </LemonMarkdown>
                    ) : item.id === '__streaming__' ? (
                        <LemonSkeleton active className="my-1" />
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

    if (displayItems.length === 0) {
        return (
            <div className="border rounded p-4">
                <div className="flex flex-col items-center justify-center h-24 text-muted">
                    <IconMessage className="text-3xl mb-2 opacity-40" />
                    <p>Run your prompt to see results</p>
                    <p className="text-xs opacity-60">Press Cmd+Enter from any message</p>
                </div>
            </div>
        )
    }

    return (
        <div className="border rounded p-4">
            <LemonTable dataSource={displayItems} columns={columns} rowKey="id" loading={submitting} embedded />
        </div>
    )
}
