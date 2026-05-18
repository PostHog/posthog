import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React from 'react'

import {
    IconChevronRight,
    IconGear,
    IconPencil,
    IconPlay,
    IconPlus,
    IconRevert,
    IconStack,
    IconTrash,
    IconWrench,
    IconCopy,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDropdown,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    Spinner,
    Link,
    LemonDivider,
} from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { humanFriendlyDuration } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { JSONEditor } from '../components/JSONEditor'
import { MetadataHeader } from '../ConversationDisplay/MetadataHeader'
import { getModelPickerFooterLink, ModelPicker, parseTrialProviderKeyId } from '../ModelPicker'
import { modelPickerLogic } from '../modelPickerLogic'
import { llmPlaygroundModelLogic } from './llmPlaygroundModelLogic'
import {
    getLinkedSourceLabel,
    llmPlaygroundPromptsLogic,
    type Message,
    type MessageRole,
    type PromptConfig,
} from './llmPlaygroundPromptsLogic'
import { llmPlaygroundRunLogic, type ComparisonItem, type UsageSummary } from './llmPlaygroundRunLogic'
import { PlaygroundSaveMenu } from './PlaygroundSaveMenu'

// Cap inline JSON previews at 20 lines so they don't dominate the layout
const INLINE_JSON_MAX_LINES = 20
const INLINE_JSON_MAX_HEIGHT_CLASS = 'max-h-[420px] overflow-y-auto'
const TOOLS_MODAL_EDITOR_HEIGHT = 460
const EXAMPLE_TOOL = [
    {
        type: 'function',
        function: {
            name: 'get_weather',
            description: 'Get the current weather for a location',
            parameters: {
                type: 'object',
                properties: {
                    location: {
                        type: 'string',
                        description: 'City and state, e.g. San Francisco, CA',
                    },
                    unit: {
                        type: 'string',
                        enum: ['celsius', 'fahrenheit'],
                    },
                },
                required: ['location'],
            },
        },
    },
]

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
    logic: llmPlaygroundPromptsLogic,
    productKey: ProductKey.LLM_ANALYTICS,
}

export function LLMAnalyticsPlaygroundScene({ tabId }: { tabId?: string }): JSX.Element {
    const promptsLogic = llmPlaygroundPromptsLogic({ tabId })
    const modelLogic = llmPlaygroundModelLogic({ tabId })
    const runLogic = llmPlaygroundRunLogic({ tabId })

    // Attach child logics to the prompts logic so they persist across tab switches
    useAttachedLogic(modelLogic, promptsLogic)
    useAttachedLogic(runLogic, promptsLogic)

    return (
        <BindLogic logic={llmPlaygroundPromptsLogic} props={{ tabId }}>
            <BindLogic logic={llmPlaygroundModelLogic} props={{ tabId }}>
                <BindLogic logic={llmPlaygroundRunLogic} props={{ tabId }}>
                    <SceneContent className="h-full">
                        <SceneTitleSection
                            name={sceneConfigurations[Scene.LLMAnalyticsPlayground].name}
                            description="Test and experiment with LLM prompts in a sandbox environment."
                            resourceType={{
                                type: sceneConfigurations[Scene.LLMAnalyticsPlayground].iconType || 'llm_analytics',
                            }}
                            actions={<PlaygroundHeaderActions />}
                        />
                        <div className="flex h-full flex-1 flex-col min-h-0">
                            <PlaygroundLayout />
                        </div>
                    </SceneContent>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function PlaygroundHeaderActions(): JSX.Element {
    const { hasRunnablePrompts, promptConfigs } = useValues(llmPlaygroundPromptsLogic)
    const { addPromptConfig, resetPlayground } = useActions(llmPlaygroundPromptsLogic)
    const { submitting: playgroundSubmitting } = useValues(llmPlaygroundRunLogic)
    const { submitPrompt, abortRun } = useActions(llmPlaygroundRunLogic)
    const firstPromptId = promptConfigs[0]?.id

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconRevert />}
                onClick={resetPlayground}
                disabledReason={playgroundSubmitting ? 'Generating...' : undefined}
                tooltip="Reset playground to default state"
                data-attr="llma-playground-reset"
            />
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPlus />}
                onClick={() => addPromptConfig(firstPromptId)}
                disabledReason={playgroundSubmitting ? 'Generating...' : undefined}
                data-attr="llma-playground-add-prompt"
            >
                Add prompt
            </LemonButton>
            <LemonButton
                type={playgroundSubmitting ? 'secondary' : 'primary'}
                size="small"
                icon={playgroundSubmitting ? <Spinner textColored /> : <IconPlay />}
                status={playgroundSubmitting ? 'danger' : undefined}
                onClick={() => (playgroundSubmitting ? abortRun() : submitPrompt())}
                disabledReason={
                    playgroundSubmitting
                        ? undefined
                        : !hasRunnablePrompts
                          ? 'Add messages to at least one prompt'
                          : undefined
                }
                data-attr="llma-playground-run-button"
            >
                {playgroundSubmitting ? 'Stop' : 'Run'}
            </LemonButton>
        </>
    )
}

function usePromptConfig(promptId: string): PromptConfig | null {
    const { promptConfigs } = useValues(llmPlaygroundPromptsLogic)
    return promptConfigs.find((prompt) => prompt.id === promptId) ?? null
}

function RateLimitBanner(): JSX.Element | null {
    const { rateLimitedUntil } = useValues(llmPlaygroundRunLogic)
    const { hasByokKeys } = useValues(modelPickerLogic)

    if (rateLimitedUntil === null || Date.now() >= rateLimitedUntil) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mb-4">
            You've hit the playground request limit for shared keys. You can make another request in{' '}
            <strong>{humanFriendlyDuration(Math.ceil((rateLimitedUntil - Date.now()) / 1000), { maxUnits: 1 })}</strong>
            .
            {!hasByokKeys && (
                <>
                    {' '}
                    <Link to={urls.settings('environment-llm-analytics', 'llm-analytics-byok')}>
                        Add your own API key
                    </Link>{' '}
                    to get higher rate limits.
                </>
            )}
        </LemonBanner>
    )
}

function SubscriptionRequiredBanner(): JSX.Element | null {
    const { subscriptionRequired } = useValues(llmPlaygroundRunLogic)

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
    const { sourceSetupLoading } = useValues(llmPlaygroundPromptsLogic)

    return (
        <div className="flex flex-1 min-h-0 flex-col gap-4">
            <RateLimitBanner />
            <SubscriptionRequiredBanner />

            <section className="rounded overflow-hidden min-h-0 flex flex-1 flex-col bg-transparent">
                {sourceSetupLoading ? (
                    <div className="h-full min-h-0 p-4 space-y-3">
                        <LemonSkeleton className="h-8 w-56" />
                        <LemonSkeleton className="h-28 w-full" />
                        <LemonSkeleton className="h-28 w-full" />
                    </div>
                ) : (
                    <div className="h-full min-h-0 overflow-y-auto">
                        <PromptConfigsSection />
                    </div>
                )}
            </section>
        </div>
    )
}

function PromptConfigsSection(): JSX.Element {
    const { promptConfigs } = useValues(llmPlaygroundPromptsLogic)
    const { removePromptConfig } = useActions(llmPlaygroundPromptsLogic)
    const { comparisonItems } = useValues(llmPlaygroundRunLogic)

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
                    return (
                        <React.Fragment key={prompt.id}>
                            <PromptCard
                                prompt={prompt}
                                index={index}
                                promptCount={promptCount}
                                canRemove={promptConfigs.length > 1}
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
    promptCount,
    canRemove,
    onRemove,
}: {
    prompt: PromptConfig
    index: number
    promptCount: number
    canRemove: boolean
    onRemove: () => void
}): JSX.Element {
    const { submitting } = useValues(llmPlaygroundRunLogic)
    const showHeaderRow = promptCount > 1 || canRemove
    const messagesRef = React.useRef<HTMLDivElement>(null)

    return (
        <div className="min-w-0 border rounded p-4 bg-transparent group/prompt ring-1 ring-primary/40 shadow-sm h-full flex flex-col min-h-0">
            {showHeaderRow ? (
                <div className="flex items-center justify-between mb-4 gap-2 shrink-0">
                    {promptCount > 1 ? (
                        <LemonTag type="highlight" size="small">
                            Prompt {index + 1}
                        </LemonTag>
                    ) : (
                        <span />
                    )}

                    {canRemove && (
                        <div>
                            <LemonButton
                                size="small"
                                status="danger"
                                icon={<IconTrash />}
                                noPadding
                                disabledReason={submitting ? 'Generating...' : undefined}
                                onClick={onRemove}
                                data-attr="llma-playground-remove-prompt"
                            />
                        </div>
                    )}
                </div>
            ) : null}

            <div className="shrink-0 mb-4">
                <ModelConfigBar promptId={prompt.id} />
            </div>

            <div ref={messagesRef} className="min-h-0 flex-1 overflow-y-auto pr-1">
                <MessagesSection promptId={prompt.id} />
            </div>

            <MessageActions promptId={prompt.id} scrollContainerRef={messagesRef} />
        </div>
    )
}

function hasUsage(usage: UsageSummary | undefined): boolean {
    if (!usage) {
        return false
    }
    return Object.values(usage).some((value) => typeof value === 'number' && value > 0)
}

function PromptResultCard({ item }: { item?: ComparisonItem }): JSX.Element {
    const isStreaming = !!item && item.latencyMs == null && !item.error
    const { addResultToConversation } = useActions(llmPlaygroundPromptsLogic)
    const canAddToConversation = !!item?.response && !item.error && !isStreaming

    const handleAddToConversation = (): void => {
        if (!item?.response) {
            return
        }
        addResultToConversation(item.response, item.promptId)
    }

    return (
        <div className="mb-4 border rounded p-4 bg-transparent h-[30vh] min-w-0 flex flex-col">
            <div className="flex items-center justify-between gap-2 mb-3">
                <LemonTag type="default" size="small">
                    Result
                </LemonTag>
                {item ? (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={handleAddToConversation}
                        disabledReason={
                            canAddToConversation
                                ? undefined
                                : isStreaming
                                  ? 'Wait for the response to finish'
                                  : item.error
                                    ? 'Only successful responses can be added'
                                    : 'No response to add'
                        }
                        tooltip="Adds this result as an assistant message and starts a blank user message for the next turn."
                        data-attr="llma-playground-add-result-to-conversation"
                    >
                        Add to conversation
                    </LemonButton>
                ) : null}
            </div>

            {!item ? (
                <div className="text-xs text-muted flex-1 min-h-[96px] flex flex-col items-center justify-center border border-dashed rounded bg-surface-primary gap-2">
                    <IconPlay className="w-5 h-5 opacity-20" />
                    <span>Run prompt to see result</span>
                </div>
            ) : (
                <>
                    <div
                        className={`flex-1 min-h-0 overflow-y-auto overflow-x-hidden text-xs whitespace-normal break-words [overflow-wrap:anywhere] p-3 min-w-0 rounded border bg-surface-primary leading-5 ${
                            item.error ? 'text-danger' : ''
                        }`}
                    >
                        {item.response ? (
                            <LemonMarkdown className="whitespace-pre-wrap break-words [&_img]:max-w-full [&_img]:h-auto [&_img]:rounded [&_img]:my-2">
                                {item.response}
                            </LemonMarkdown>
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
                    {(!!item.response || hasUsage(item.usage)) && (
                        <MetadataHeader
                            className="mt-2 pt-2"
                            isError={item.error}
                            inputTokens={item.usage?.prompt_tokens ?? undefined}
                            outputTokens={item.usage?.completion_tokens ?? undefined}
                            cacheReadTokens={item.usage?.cache_read_tokens ?? undefined}
                            cacheWriteTokens={item.usage?.cache_write_tokens ?? undefined}
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

function getTrialModelsErrorMessage(errorStatus: number | null): string | null {
    if (errorStatus === null) {
        return null
    }
    if (errorStatus === 429) {
        return 'Too many requests. Please wait a moment and try again.'
    }
    return 'Failed to load models. Please refresh the page or try again later.'
}

function PlaygroundModelPicker({ promptId }: { promptId: string }): JSX.Element {
    const prompt = usePromptConfig(promptId)
    const { effectiveModelOptions, trialModelsErrorStatus } = useValues(llmPlaygroundModelLogic)
    const {
        hasByokKeys,
        providerModelGroups,
        trialProviderModelGroups,
        byokModelsLoading,
        trialModelsLoading,
        providerKeysLoading,
    } = useValues(modelPickerLogic)
    const { loadTrialModels } = useActions(modelPickerLogic)
    const { setModel } = useActions(llmPlaygroundPromptsLogic)

    if (!prompt) {
        return <LemonSkeleton className="h-10" />
    }

    const selectedModel = effectiveModelOptions.find((m) => m.id === prompt.model)
    const groups = hasByokKeys ? providerModelGroups : trialProviderModelGroups
    const loading = hasByokKeys ? byokModelsLoading || providerKeysLoading : trialModelsLoading
    const errorMessage = !hasByokKeys ? getTrialModelsErrorMessage(trialModelsErrorStatus) : null
    const showError = !hasByokKeys && effectiveModelOptions.length === 0 && !trialModelsLoading

    return (
        <>
            <ModelPicker
                model={prompt.model}
                selectedProviderKeyId={prompt.selectedProviderKeyId}
                onSelect={(modelId, providerKeyId) => {
                    const trialProvider = parseTrialProviderKeyId(providerKeyId)
                    posthog.capture('llma playground model changed', {
                        model: modelId,
                        is_byok: !trialProvider,
                    })
                    setModel(modelId, trialProvider ? undefined : providerKeyId, promptId)
                }}
                groups={groups}
                loading={loading}
                footerLink={getModelPickerFooterLink(hasByokKeys)}
                selectedModelName={selectedModel?.name}
                data-attr={`llma-playground-model-selector-${promptId}`}
            />
            {showError && (
                <div className="mt-1">
                    <p className="text-xs text-danger">{errorMessage || 'No models available.'}</p>
                    <button
                        type="button"
                        className="text-xs text-link mt-1 underline"
                        onClick={() => loadTrialModels()}
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
    const { setMaxTokens, setTemperature, setTopP, setThinking, setReasoningLevel } =
        useActions(llmPlaygroundPromptsLogic)

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
                <label className="text-xs font-medium mb-1 block">Temperature</label>
                <LemonInput
                    type="number"
                    value={prompt.temperature ?? undefined}
                    onChange={(val) => setTemperature(val ?? null, promptId)}
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
                    value={prompt.topP ?? undefined}
                    onChange={(val) => setTopP(val ?? null, promptId)}
                    min={0}
                    max={1}
                    step={0.05}
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
                tooltip="Enable thinking/reasoning stream (model must support extended thinking)"
            />
        </div>
    )
}

function ModelConfigBar({ promptId }: { promptId: string }): JSX.Element {
    const prompt = usePromptConfig(promptId)

    if (!prompt) {
        return <LemonSkeleton className="h-8" />
    }

    const hasNonDefaultSettings =
        prompt.maxTokens !== null ||
        prompt.temperature !== null ||
        prompt.topP !== null ||
        prompt.thinking ||
        prompt.reasoningLevel !== 'medium'

    return (
        <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1 min-w-[260px] max-w-lg">
                <PlaygroundModelPicker promptId={promptId} />
            </div>

            <LemonDropdown
                overlay={<SettingsDropdownOverlay promptId={promptId} />}
                closeOnClickInside={false}
                placement="bottom-end"
                onVisibilityChange={(visible) => {
                    if (!visible && prompt) {
                        posthog.capture('llma playground parameters configured', {
                            max_tokens: prompt.maxTokens,
                            temperature: prompt.temperature,
                            top_p: prompt.topP,
                            reasoning_level: prompt.reasoningLevel,
                            thinking: prompt.thinking,
                        })
                    }
                }}
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

    if (!prompt) {
        return <LemonSkeleton className="h-16" />
    }

    return (
        <div className="space-y-3">
            <SystemMessageDisplay promptId={promptId} />
            {prompt.messages.map((message, index) => (
                <MessageDisplay key={`${promptId}-${index}`} promptId={promptId} index={index} message={message} />
            ))}
        </div>
    )
}

function MessageActions({
    promptId,
    scrollContainerRef,
}: {
    promptId: string
    scrollContainerRef: React.RefObject<HTMLDivElement | null>
}): JSX.Element {
    const { submitting } = useValues(llmPlaygroundRunLogic)
    const { addMessage } = useActions(llmPlaygroundPromptsLogic)

    const handleAddMessage = (): void => {
        addMessage(undefined, promptId)
        requestAnimationFrame(() => {
            const el = scrollContainerRef.current
            if (el) {
                el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
            }
        })
    }

    return (
        <div className="flex items-center gap-2 shrink-0 mt-3">
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPlus />}
                onClick={handleAddMessage}
                disabledReason={submitting ? 'Generating...' : undefined}
            >
                Message
            </LemonButton>
            <ToolsButton promptId={promptId} />
        </div>
    )
}

function ToolsButton({ promptId }: { promptId: string }): JSX.Element {
    const prompt = usePromptConfig(promptId)
    const { submitting } = useValues(llmPlaygroundRunLogic)
    const { editModal, localToolsJsonByPromptId, toolsJsonErrorByPromptId } = useValues(llmPlaygroundPromptsLogic)
    const { setTools, setLocalToolsJson, setEditModal, setToolsJsonError } = useActions(llmPlaygroundPromptsLogic)

    if (!prompt) {
        return <LemonSkeleton className="h-7 w-20" />
    }

    const showEditModal = editModal?.type === 'tools' && editModal.promptId === promptId
    const jsonError = toolsJsonErrorByPromptId[promptId] ?? null
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
            setToolsJsonError(promptId, null)
        } catch (e) {
            setToolsJsonError(promptId, e instanceof SyntaxError ? e.message : 'Invalid JSON')
        }
    }

    return (
        <>
            <LemonButton
                type={hasTools ? 'primary' : 'secondary'}
                size="small"
                icon={<IconWrench />}
                active={hasTools}
                onClick={() => setEditModal({ type: 'tools', promptId })}
                disabledReason={submitting ? 'Generating...' : undefined}
                tooltip={hasTools ? `${toolCount} tool${toolCount === 1 ? '' : 's'} attached` : 'No tools attached'}
            >
                Tools
            </LemonButton>

            <LemonModal
                isOpen={showEditModal}
                onClose={() => setEditModal(null)}
                title="Tools"
                description="Define functions the model can call during generation. Tools use the OpenAI function calling format."
                width="90vw"
                maxWidth={640}
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
                        <LemonButton type="secondary" onClick={() => setEditModal(null)}>
                            Close
                        </LemonButton>
                    </div>
                }
            >
                <div className="space-y-2">
                    <div className="flex items-center justify-between">
                        <label className="font-semibold block text-sm">Tools (JSON)</label>
                        {!hasTools && (
                            <button
                                type="button"
                                className="text-xs text-link"
                                onClick={() => {
                                    posthog.capture('llma playground tools example inserted')
                                    const exampleJson = JSON.stringify(EXAMPLE_TOOL, null, 2)
                                    handleToolsChange(exampleJson)
                                    setLocalToolsJson(exampleJson, promptId)
                                }}
                            >
                                Insert example
                            </button>
                        )}
                    </div>
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
                    {jsonError ? (
                        <div className="text-xs text-danger">{jsonError}</div>
                    ) : (
                        <div className="text-xs text-muted">
                            A JSON array of tool definitions following the{' '}
                            <Link
                                to="https://developers.openai.com/api/docs/guides/function-calling"
                                target="_blank"
                                className="text-xs"
                            >
                                OpenAI function calling format
                            </Link>
                            . Each tool needs a <code className="text-xs">type</code>,{' '}
                            <code className="text-xs">function.name</code>,{' '}
                            <code className="text-xs">function.description</code>, and{' '}
                            <code className="text-xs">function.parameters</code>.
                        </div>
                    )}
                </div>
            </LemonModal>
        </>
    )
}

function SystemMessageDisplay({ promptId }: { promptId: string }): JSX.Element {
    const prompt = usePromptConfig(promptId)
    const { promptConfigs, editModal, collapsedSections, linkedSource } = useValues(llmPlaygroundPromptsLogic)
    const { setSystemPrompt, setEditModal, toggleCollapsed } = useActions(llmPlaygroundPromptsLogic)
    const { submitPrompt } = useActions(llmPlaygroundRunLogic)

    if (!prompt) {
        return <LemonSkeleton className="h-12" />
    }

    const showEditModal = editModal?.type === 'system' && editModal.promptId === promptId
    const collapsed = !!collapsedSections[`system:${promptId}`]
    const hasOtherPrompts = promptConfigs.length > 1

    const linkedContextLabel = getLinkedSourceLabel(linkedSource)

    const copySystemPromptToOtherPrompts = (): void => {
        if (!hasOtherPrompts) {
            return
        }

        posthog.capture('llma playground system prompt synced', {
            target_prompt_count: promptConfigs.length - 1,
        })
        for (const otherPrompt of promptConfigs) {
            if (otherPrompt.id !== promptId) {
                setSystemPrompt(prompt.systemPrompt, otherPrompt.id)
            }
        }
    }

    return (
        <>
            <div className="border rounded p-4 py-2 relative group border-l-4 border-l-[var(--color-purple-500)]">
                <div className="absolute top-2 right-2 flex items-center gap-1">
                    <PlaygroundSaveMenu prompt={prompt} />
                    <LemonDivider vertical className="h-5 mx-0.5" />
                    <LemonButton
                        size="small"
                        icon={<IconCopy />}
                        tooltip="Copy system prompt"
                        noPadding
                        onClick={() => {
                            posthog.capture('llma playground response copied', { content_type: 'system_prompt' })
                            void copyToClipboard(prompt.systemPrompt, 'system prompt')
                        }}
                        data-attr="llma-playground-copy-system-prompt"
                    />
                    {hasOtherPrompts && (
                        <LemonButton
                            size="small"
                            icon={<IconStack />}
                            tooltip="Apply this system prompt to other prompts"
                            noPadding
                            onClick={copySystemPromptToOtherPrompts}
                            data-attr="llma-playground-sync-system-prompt"
                        />
                    )}
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit system prompt in modal"
                        noPadding
                        onClick={() => setEditModal({ type: 'system', promptId })}
                        data-attr="llma-playground-edit-system-prompt"
                    />
                </div>

                <div
                    className={`flex items-center gap-2 cursor-pointer ${collapsed ? 'mb-0' : 'mb-2'}`}
                    onClick={() => toggleCollapsed(`system:${promptId}`)}
                >
                    <CollapsibleChevron collapsed={collapsed} />
                    <LemonTag type="completion" size="small">
                        System
                    </LemonTag>
                    {linkedContextLabel ? (
                        <LemonTag type="highlight" size="small" className="max-w-[260px] truncate">
                            Editing {linkedContextLabel}
                        </LemonTag>
                    ) : null}
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
                onClose={() => setEditModal(null)}
                title="Edit system prompt"
                width="90vw"
                maxWidth="1200px"
                footer={
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={() => setEditModal(null)}>
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
    const { editModal, collapsedSections } = useValues(llmPlaygroundPromptsLogic)
    const { updateMessage, deleteMessage, setEditModal, toggleCollapsed } = useActions(llmPlaygroundPromptsLogic)
    const { submitPrompt } = useActions(llmPlaygroundRunLogic)

    const messageKey = `message:${promptId}:${index}`
    const collapsed = !!collapsedSections[messageKey]
    const showEditModal =
        editModal?.type === 'message' && editModal.promptId === promptId && editModal.messageIndex === index

    const handleRoleChange = (newRole: MessageRole): void => {
        posthog.capture('llma playground message role changed', { from: message.role, to: newRole })
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
                <div className="absolute top-4 right-4 flex items-center gap-1">
                    <LemonButton
                        size="small"
                        icon={<IconCopy />}
                        tooltip="Copy message"
                        noPadding
                        onClick={() => {
                            posthog.capture('llma playground response copied', {
                                content_type: message.role === 'assistant' ? 'assistant_message' : 'user_message',
                            })
                            void copyToClipboard(message.content, `${message.role} message`)
                        }}
                    />
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit message in modal"
                        noPadding
                        onClick={() => setEditModal({ type: 'message', promptId, messageIndex: index })}
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
                    onClick={() => toggleCollapsed(messageKey)}
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
                onClose={() => setEditModal(null)}
                title="Edit message"
                width="90vw"
                maxWidth="1200px"
                footer={
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={() => setEditModal(null)}>
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
