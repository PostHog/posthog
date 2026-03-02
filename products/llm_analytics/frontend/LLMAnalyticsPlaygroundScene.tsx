import { useActions, useMountedLogic, useValues } from 'kea'
import React, { useState } from 'react'

import {
    IconChevronRight,
    IconCopy,
    IconGear,
    IconPencil,
    IconPlay,
    IconPlus,
    IconStack,
    IconTrash,
    IconWrench,
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
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { humanFriendlyDuration } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SceneExport } from 'scenes/sceneTypes'

import { ByokModelPicker } from './ByokModelPicker'
import { JSONEditor } from './components/JSONEditor'
import { MetadataHeader } from './ConversationDisplay/MetadataHeader'
import {
    ComparisonItem,
    Message,
    MessageRole,
    PromptConfig,
    llmAnalyticsPlaygroundLogic,
} from './llmAnalyticsPlaygroundLogic'
const INLINE_JSON_MAX_LINES = 20
const INLINE_JSON_MAX_HEIGHT_CLASS = 'max-h-[420px] overflow-y-auto'
const TOOLS_MODAL_EDITOR_HEIGHT = 460

function CollapsibleChevron({ collapsed }: { collapsed: boolean }): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            noPadding
            className="h-5 w-5 [&_svg]:h-3.5 [&_svg]:w-3.5"
            icon={<IconChevronRight className={`transition-transform ${collapsed ? 'rotate-0' : 'rotate-90'}`} />}
        />
    )
}

export const scene: SceneExport = {
    component: LLMAnalyticsPlaygroundScene,
    logic: llmAnalyticsPlaygroundLogic,
}

export function LLMAnalyticsPlaygroundScene(): JSX.Element {
    useMountedLogic(llmAnalyticsPlaygroundLogic)

    // 300px accounts for the top nav bar, scene title section, tab bar, and surrounding padding
    return (
        <div className="flex flex-col h-[calc(100vh-300px)] min-h-[520px]">
            <PlaygroundLayout />
        </div>
    )
}

function usePromptConfig(promptId: string): PromptConfig | null {
    const { promptConfigs } = useValues(llmAnalyticsPlaygroundLogic)
    return promptConfigs.find((prompt) => prompt.id === promptId) ?? null
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
        <div className="flex flex-1 min-h-0 flex-col gap-4">
            <RateLimitBanner />
            <SubscriptionRequiredBanner />

            <section className="rounded overflow-hidden min-h-0 flex flex-1 flex-col bg-transparent">
                <div className="h-full min-h-0 overflow-y-auto">
                    <PromptConfigsSection />
                </div>
            </section>
        </div>
    )
}

function PromptConfigsSection(): JSX.Element {
    const { promptConfigs, activePromptId, comparisonItems } = useValues(llmAnalyticsPlaygroundLogic)
    const { removePromptConfig, setActivePromptId } = useActions(llmAnalyticsPlaygroundLogic)

    const promptCount = promptConfigs.length
    const gridMinWidth = `calc(${promptCount} * 500px + ${Math.max(promptCount - 1, 0)} * 1rem)`
    const latestItemByPromptId = new Map<string, ComparisonItem>()

    for (const item of comparisonItems) {
        if (item.promptId) {
            latestItemByPromptId.set(item.promptId, item)
        }
    }

    return (
        <div className="h-full min-h-0 overflow-x-auto">
            <div
                className="grid h-full min-w-full items-stretch gap-4"
                style={{
                    width: `max(100%, ${gridMinWidth})`,
                    gridAutoFlow: 'column',
                    gridTemplateColumns: `repeat(${promptCount}, minmax(500px, 1fr))`,
                    gridTemplateRows: 'minmax(0, 1fr) auto',
                }}
            >
                {promptConfigs.map((prompt, index) => {
                    const isActive = prompt.id === activePromptId
                    return (
                        <React.Fragment key={prompt.id}>
                            <PromptCard
                                prompt={prompt}
                                index={index}
                                isActive={isActive}
                                canRemove={promptConfigs.length > 1}
                                onActivate={() => setActivePromptId(prompt.id)}
                                onRemove={() => removePromptConfig(prompt.id)}
                            />
                            <PromptResultCard item={latestItemByPromptId.get(prompt.id)} />
                        </React.Fragment>
                    )
                })}
            </div>
        </div>
    )
}

function PromptCard({
    prompt,
    index,
    isActive,
    canRemove,
    onActivate,
    onRemove,
}: {
    prompt: PromptConfig
    index: number
    isActive: boolean
    canRemove: boolean
    onActivate: () => void
    onRemove: () => void
}): JSX.Element {
    const { submitting } = useValues(llmAnalyticsPlaygroundLogic)

    return (
        <div
            className={`min-w-0 border rounded p-4 bg-transparent transition-shadow group/prompt ${
                isActive ? 'ring-1 ring-primary/40 shadow-sm' : 'hover:shadow-sm'
            } h-full flex flex-col min-h-0`}
        >
            <div className="flex items-center justify-between mb-4 gap-2 shrink-0">
                <button type="button" className="flex items-center gap-2 min-w-0" onClick={onActivate}>
                    <LemonTag type={isActive ? 'highlight' : 'default'} size="small">
                        Prompt {index + 1}
                    </LemonTag>
                </button>

                {canRemove && (
                    <div className="opacity-0 group-hover/prompt:opacity-100 group-focus-within/prompt:opacity-100 transition-opacity">
                        <LemonButton
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            noPadding
                            disabledReason={submitting ? 'Generating...' : undefined}
                            onClick={onRemove}
                            data-attr="playground-remove-prompt"
                        />
                    </div>
                )}
            </div>

            <div className="shrink-0 mb-4">
                <ModelConfigBar promptId={prompt.id} />
            </div>

            <div className="min-h-0 overflow-y-auto pr-1">
                <MessagesSection promptId={prompt.id} />
            </div>
        </div>
    )
}

function PromptResultCard({ item }: { item?: ComparisonItem }): JSX.Element {
    const isStreaming = !!item && item.latencyMs == null && !item.error

    return (
        <div className="border rounded p-4 bg-transparent h-[300px] min-w-0 flex flex-col">
            <div className="flex items-center justify-between gap-2 mb-3">
                <LemonTag type="default" size="small">
                    Result
                </LemonTag>
            </div>

            {!item ? (
                <div className="text-xs text-muted flex-1 min-h-[96px] flex flex-col items-center justify-center border border-dashed rounded bg-surface-primary gap-2">
                    <IconPlay className="w-5 h-5 opacity-20" />
                    <span>Run prompt to see result</span>
                </div>
            ) : (
                <>
                    <div
                        className={`flex-1 min-h-0 overflow-y-auto overflow-x-hidden text-xs whitespace-normal break-words p-3 min-w-0 rounded border bg-surface-primary leading-5 ${
                            item.error ? 'text-danger' : ''
                        }`}
                        style={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}
                    >
                        {item.response ? (
                            <div className="whitespace-pre-wrap break-words">{item.response}</div>
                        ) : isStreaming ? (
                            <div className="h-full flex items-center justify-center text-xs text-muted">
                                <div className="inline-flex items-center gap-2">
                                    <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                                    <span>Generating response...</span>
                                </div>
                            </div>
                        ) : (
                            <span className="text-muted italic">No response</span>
                        )}
                    </div>
                    {!!item.response && (
                        <MetadataHeader
                            className="mt-2 pt-2"
                            isError={item.error}
                            inputTokens={item.usage?.prompt_tokens ?? undefined}
                            outputTokens={item.usage?.completion_tokens ?? undefined}
                            latency={typeof item.latencyMs === 'number' ? item.latencyMs / 1000 : undefined}
                            timeToFirstToken={typeof item.ttftMs === 'number' ? item.ttftMs / 1000 : undefined}
                            isStreaming={isStreaming}
                        />
                    )}
                </>
            )}
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

function ModelPicker({ promptId }: { promptId: string }): JSX.Element {
    const prompt = usePromptConfig(promptId)
    const {
        effectiveModelOptions,
        hasByokKeys,
        modelOptions,
        modelOptionsLoading,
        modelOptionsErrorStatus,
        groupedModelOptions,
    } = useValues(llmAnalyticsPlaygroundLogic)
    const { setModel, loadModelOptions } = useActions(llmAnalyticsPlaygroundLogic)

    if (!prompt) {
        return <LemonSkeleton className="h-10" />
    }

    if (hasByokKeys) {
        const options = Array.isArray(effectiveModelOptions) ? effectiveModelOptions : []
        const selectedModel = options.find((m) => m.id === prompt.model)

        return (
            <ByokModelPicker
                model={prompt.model}
                selectedProviderKeyId={prompt.selectedProviderKeyId}
                onSelect={(modelId, providerKeyId) => setModel(modelId, providerKeyId, promptId)}
                selectedModelName={selectedModel?.name}
                data-attr={`playground-model-selector-${promptId}`}
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
                    value={prompt.model}
                    onChange={(value) => value && setModel(value, undefined, promptId)}
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
                    data-attr={`playground-model-selector-${promptId}`}
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

function SettingsDropdownOverlay({ promptId }: { promptId: string }): JSX.Element {
    const prompt = usePromptConfig(promptId)
    const { setMaxTokens, setThinking, setReasoningLevel } = useActions(llmAnalyticsPlaygroundLogic)

    if (!prompt) {
        return <div className="p-3 text-xs text-muted">Prompt not found</div>
    }

    return (
        <div className="space-y-4 p-4 w-[300px]">
            <div>
                <label className="text-xs font-medium mb-1 block">Max tokens</label>
                <LemonInput
                    type="number"
                    value={prompt.maxTokens ?? undefined}
                    onChange={(val) => setMaxTokens(val ?? null, promptId)}
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
                    value={prompt.reasoningLevel}
                    onChange={(value) => setReasoningLevel(value ?? null, promptId)}
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
                checked={prompt.thinking}
                onChange={(checked) => setThinking(checked, promptId)}
                label="Thinking"
                size="small"
                tooltip="Enable thinking/reasoning stream (if supported)"
            />
        </div>
    )
}

function ModelConfigBar({ promptId }: { promptId: string }): JSX.Element {
    const prompt = usePromptConfig(promptId)

    if (!prompt) {
        return <LemonSkeleton className="h-8" />
    }

    const hasNonDefaultSettings = prompt.maxTokens !== null || prompt.thinking || prompt.reasoningLevel !== 'medium'

    return (
        <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1 min-w-[260px] max-w-lg">
                <ModelPicker promptId={promptId} />
            </div>

            <LemonDropdown
                overlay={<SettingsDropdownOverlay promptId={promptId} />}
                closeOnClickInside={false}
                placement="bottom-end"
            >
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

function MessagesSection({ promptId }: { promptId: string }): JSX.Element {
    const prompt = usePromptConfig(promptId)
    const { submitting } = useValues(llmAnalyticsPlaygroundLogic)
    const { addMessage } = useActions(llmAnalyticsPlaygroundLogic)

    if (!prompt) {
        return <LemonSkeleton className="h-16" />
    }

    return (
        <div className="space-y-3">
            <SystemMessageDisplay promptId={promptId} />
            {prompt.messages.map((message, index) => (
                <MessageDisplay key={`${promptId}-${index}`} promptId={promptId} index={index} message={message} />
            ))}
            <div className="flex items-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => addMessage(undefined, promptId)}
                    disabledReason={submitting ? 'Generating...' : undefined}
                >
                    Message
                </LemonButton>
                <ToolsButton promptId={promptId} />
            </div>
        </div>
    )
}

function ToolsButton({ promptId }: { promptId: string }): JSX.Element {
    const prompt = usePromptConfig(promptId)
    const { submitting, localToolsJsonByPromptId } = useValues(llmAnalyticsPlaygroundLogic)
    const { setTools, setLocalToolsJson } = useActions(llmAnalyticsPlaygroundLogic)
    const [showEditModal, setShowEditModal] = useState(false)
    const [jsonError, setJsonError] = useState<string | null>(null)

    if (!prompt) {
        return <LemonSkeleton className="h-7 w-20" />
    }

    const localToolsJson = localToolsJsonByPromptId[promptId] ?? null
    const toolsJsonString = localToolsJson ?? JSON.stringify(prompt.tools ?? [], null, 2)
    const toolCount = Array.isArray(prompt.tools) ? prompt.tools.length : 0
    const hasTools = toolCount > 0

    const handleToolsChange = (value?: string): void => {
        if (value === undefined) {
            return
        }
        setLocalToolsJson(value, promptId)
        try {
            const parsedTools = JSON.parse(value)
            setTools(parsedTools, promptId)
            setJsonError(null)
        } catch (e) {
            setJsonError(e instanceof SyntaxError ? e.message : 'Invalid JSON')
        }
    }

    return (
        <>
            <LemonButton
                type={hasTools ? 'primary' : 'secondary'}
                size="small"
                icon={<IconWrench />}
                active={hasTools}
                onClick={() => setShowEditModal(true)}
                disabledReason={submitting ? 'Generating...' : undefined}
                tooltip={hasTools ? `${toolCount} tool${toolCount === 1 ? '' : 's'} attached` : 'No tools attached'}
            >
                Tools
            </LemonButton>

            <LemonModal
                isOpen={showEditModal}
                onClose={() => setShowEditModal(false)}
                title="Edit tools"
                width="90vw"
                maxWidth="1200px"
                footer={
                    <div className="flex justify-end gap-2">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() => {
                                setTools(null, promptId)
                                setLocalToolsJson(null, promptId)
                            }}
                            disabledReason={!prompt.tools ? 'No tools to remove' : undefined}
                        >
                            Clear tools
                        </LemonButton>
                        <LemonButton type="secondary" onClick={() => setShowEditModal(false)}>
                            Close
                        </LemonButton>
                    </div>
                }
            >
                <div className="space-y-2">
                    <label className="font-semibold block text-sm">Tools (JSON)</label>
                    <CodeEditorResizeable
                        className="border rounded"
                        language="json"
                        value={toolsJsonString}
                        onChange={handleToolsChange}
                        height={TOOLS_MODAL_EDITOR_HEIGHT}
                        embedded
                        allowManualResize={false}
                        autoFocus
                        options={{
                            minimap: { enabled: false },
                            scrollbar: { alwaysConsumeMouseWheel: false },
                            padding: { bottom: 0, top: 10 },
                            overviewRulerLanes: 0,
                            hideCursorInOverviewRuler: true,
                            overviewRulerBorder: false,
                            glyphMargin: true,
                            folding: false,
                            lineNumbers: 'off',
                            lineDecorationsWidth: 0,
                            lineNumbersMinChars: 0,
                            renderLineHighlight: 'none',
                            cursorStyle: 'line',
                            scrollBeyondLastLine: false,
                            quickSuggestions: false,
                            contextmenu: false,
                        }}
                    />
                    <div className={`text-xs ${jsonError ? 'text-danger' : 'text-muted'}`}>
                        {jsonError ?? 'Paste or edit valid JSON tool definitions.'}
                    </div>
                </div>
            </LemonModal>
        </>
    )
}

function SystemMessageDisplay({ promptId }: { promptId: string }): JSX.Element {
    const prompt = usePromptConfig(promptId)
    const { promptConfigs } = useValues(llmAnalyticsPlaygroundLogic)
    const { setSystemPrompt, submitPrompt } = useActions(llmAnalyticsPlaygroundLogic)
    const [showEditModal, setShowEditModal] = useState(false)
    const [collapsed, setCollapsed] = useState(false)

    if (!prompt) {
        return <LemonSkeleton className="h-12" />
    }

    const hasOtherPrompts = promptConfigs.length > 1
    const copySystemPromptToOtherPrompts = (): void => {
        if (!hasOtherPrompts) {
            return
        }

        for (const otherPrompt of promptConfigs) {
            if (otherPrompt.id !== promptId) {
                setSystemPrompt(prompt.systemPrompt, otherPrompt.id)
            }
        }
    }

    return (
        <>
            <div className="border rounded p-4 py-2 relative group border-l-4 border-l-[var(--color-purple-500)]">
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
                    <LemonButton
                        size="small"
                        icon={<IconCopy />}
                        tooltip="Copy system prompt"
                        noPadding
                        onClick={() => void copyToClipboard(prompt.systemPrompt, 'system prompt')}
                        data-attr="playground-copy-system-prompt"
                    />
                    {hasOtherPrompts && (
                        <LemonButton
                            size="small"
                            icon={<IconStack />}
                            tooltip="Apply this system prompt to other prompts"
                            noPadding
                            onClick={copySystemPromptToOtherPrompts}
                            data-attr="playground-sync-system-prompt"
                        />
                    )}
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit system prompt in modal"
                        noPadding
                        onClick={() => setShowEditModal(true)}
                        data-attr="playground-edit-system-prompt"
                    />
                </div>

                <div
                    className={`flex items-center gap-2 cursor-pointer ${collapsed ? 'mb-0' : 'mb-2'}`}
                    onClick={() => setCollapsed(!collapsed)}
                >
                    <CollapsibleChevron collapsed={collapsed} />
                    <LemonTag type="completion" size="small">
                        System
                    </LemonTag>
                    {collapsed && (
                        <span className="text-xs text-muted truncate flex-1">
                            {prompt.systemPrompt
                                ? prompt.systemPrompt.slice(0, 80) + (prompt.systemPrompt.length > 80 ? '…' : '')
                                : 'No system prompt'}
                        </span>
                    )}
                </div>

                <AnimatedCollapsible collapsed={collapsed}>
                    <LemonTextArea
                        className="text-sm w-full"
                        placeholder="System instructions for the AI assistant..."
                        value={prompt.systemPrompt}
                        onChange={(value) => setSystemPrompt(value, promptId)}
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
                footer={
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={() => setShowEditModal(false)}>
                            Close
                        </LemonButton>
                    </div>
                }
            >
                <div className="space-y-4">
                    <div>
                        <label className="font-semibold mb-1 block text-sm">System instructions</label>
                        <LemonTextArea
                            className="text-sm w-full"
                            placeholder="System instructions for the AI assistant..."
                            value={prompt.systemPrompt}
                            onChange={(value) => setSystemPrompt(value, promptId)}
                            minRows={8}
                        />
                    </div>
                </div>
            </LemonModal>
        </>
    )
}

function MessageDisplay({
    promptId,
    message,
    index,
}: {
    promptId: string
    message: Message
    index: number
}): JSX.Element {
    const { updateMessage, deleteMessage, submitPrompt } = useActions(llmAnalyticsPlaygroundLogic)
    const [collapsed, setCollapsed] = useState(false)
    const [showEditModal, setShowEditModal] = useState(false)

    const handleRoleChange = (newRole: MessageRole): void => {
        updateMessage(index, { role: newRole }, promptId)
    }

    const handleContentChange = (newContent: string | undefined): void => {
        updateMessage(index, { content: newContent ?? '' }, promptId)
    }

    const roleOptions: { label: string; value: MessageRole }[] = [
        { label: 'User', value: 'user' },
        { label: 'Assistant', value: 'assistant' },
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

    const trimmedContent = message.content.trim()
    const useJsonEditor = trimmedContent.startsWith('{') || trimmedContent.startsWith('[')

    return (
        <>
            <div className={`border rounded p-4 py-2 relative group ${getRoleBorderClass(message.role)}`}>
                <div className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
                    <LemonButton
                        size="small"
                        icon={<IconCopy />}
                        tooltip="Copy message"
                        noPadding
                        onClick={() => void copyToClipboard(message.content, `${message.role} message`)}
                    />
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit message in modal"
                        noPadding
                        onClick={() => setShowEditModal(true)}
                    />
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Delete message"
                        noPadding
                        onClick={() => deleteMessage(index, promptId)}
                    />
                </div>

                <div
                    className={`flex items-center gap-2 cursor-pointer ${collapsed ? 'mb-0' : 'mb-2'}`}
                    onClick={() => setCollapsed(!collapsed)}
                >
                    <CollapsibleChevron collapsed={collapsed} />
                    <span className={`w-2 h-2 rounded-full shrink-0 ${getRoleDotClass(message.role)}`} />
                    <div onClick={(e) => e.stopPropagation()}>
                        <LemonSelect<MessageRole>
                            size="small"
                            options={roleOptions}
                            value={message.role}
                            onChange={handleRoleChange}
                            dropdownMatchSelectWidth={false}
                        />
                    </div>
                    {collapsed && (
                        <span className="text-xs text-muted truncate flex-1">
                            {message.content
                                ? message.content.slice(0, 80) + (message.content.length > 80 ? '…' : '')
                                : `Empty ${message.role} message`}
                        </span>
                    )}
                </div>

                <AnimatedCollapsible collapsed={collapsed}>
                    {useJsonEditor ? (
                        <div className={`border rounded ${INLINE_JSON_MAX_HEIGHT_CLASS}`}>
                            <JSONEditor
                                value={message.content}
                                onChange={handleContentChange}
                                defaultNumberOfLines={2}
                                maxNumberOfLines={INLINE_JSON_MAX_LINES}
                            />
                        </div>
                    ) : (
                        <LemonTextArea
                            className="text-sm w-full"
                            placeholder={`Enter ${message.role} message here...`}
                            value={message.content}
                            onChange={handleContentChange}
                            minRows={2}
                            maxRows={undefined}
                            onPressCmdEnter={() => submitPrompt()}
                        />
                    )}
                </AnimatedCollapsible>
            </div>

            <LemonModal
                isOpen={showEditModal}
                onClose={() => setShowEditModal(false)}
                title="Edit message"
                width="90vw"
                maxWidth="1200px"
                footer={
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={() => setShowEditModal(false)}>
                            Close
                        </LemonButton>
                    </div>
                }
            >
                <div className="space-y-4">
                    <div>
                        <label className="font-semibold mb-1 block text-sm">Message content</label>
                        <LemonTextArea
                            className="text-sm w-full"
                            placeholder={`Enter ${message.role} message here...`}
                            value={message.content}
                            onChange={handleContentChange}
                            minRows={8}
                        />
                    </div>
                </div>
            </LemonModal>
        </>
    )
}
