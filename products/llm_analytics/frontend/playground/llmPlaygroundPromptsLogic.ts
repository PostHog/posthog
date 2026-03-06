import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { isObject, uuid } from 'lib/utils'
import { urls } from 'scenes/urls'

import { normalizeLLMProvider } from '../settings/llmProviderKeysLogic'
import { normalizeRole } from '../utils'
import type { llmPlaygroundPromptsLogicType } from './llmPlaygroundPromptsLogicType'
import { isTraceLikeSelection } from './playgroundModelMatching'

export type MessageRole = 'user' | 'assistant' | 'system'
export type ReasoningLevel = 'minimal' | 'low' | 'medium' | 'high' | null

export interface Message {
    role: MessageRole
    content: string
}

export interface PromptConfig {
    id: string
    model: string
    selectedProviderKeyId: string | null
    systemPrompt: string
    maxTokens: number | null
    thinking: boolean
    reasoningLevel: ReasoningLevel
    tools: Record<string, unknown>[] | null
    messages: Message[]
}

export interface PlaygroundSetupPayload {
    model?: string
    provider?: string
    input?: unknown
    tools?: Record<string, unknown>[]
}

export const DEFAULT_SYSTEM_PROMPT = 'You are a helpful AI assistant.'

export function createPromptConfig(partial: Partial<PromptConfig> = {}): PromptConfig {
    return {
        id: partial.id ?? uuid(),
        model: partial.model ?? '',
        selectedProviderKeyId: partial.selectedProviderKeyId ?? null,
        systemPrompt: partial.systemPrompt ?? DEFAULT_SYSTEM_PROMPT,
        maxTokens: partial.maxTokens ?? null,
        thinking: partial.thinking ?? false,
        reasoningLevel: partial.reasoningLevel ?? 'medium',
        tools: partial.tools ?? null,
        messages: partial.messages ?? [],
    }
}

export const INITIAL_PROMPT = createPromptConfig()

function resolveTargetPromptId(promptConfigs: PromptConfig[], promptId?: string): string | null {
    if (promptId) {
        return promptId
    }
    return promptConfigs[0]?.id ?? null
}

export function updatePromptConfigs(
    state: PromptConfig[],
    promptId: string | undefined,
    updater: (prompt: PromptConfig) => PromptConfig
): PromptConfig[] {
    const targetPromptId = resolveTargetPromptId(state, promptId)
    if (!targetPromptId) {
        return state
    }
    return state.map((prompt) => (prompt.id === targetPromptId ? updater(prompt) : prompt))
}

// Input processing helpers for setupPlaygroundFromEvent

interface RawMessage {
    role: string
    content: unknown
}

type ConversationRole = 'user' | 'assistant'

enum InputMessageRole {
    User = 'user',
    Assistant = 'assistant',
    AI = 'ai',
    Model = 'model',
}

function extractTextFromMessagePart(part: unknown): string | null {
    if (!isObject(part)) {
        return null
    }

    if (typeof part.text === 'string' && part.text.trim().length > 0) {
        return part.text
    }

    if (typeof part.content === 'string' && part.content.trim().length > 0) {
        return part.content
    }

    if (typeof part.output_text === 'string' && part.output_text.trim().length > 0) {
        return part.output_text
    }

    if (typeof part.value === 'string' && part.value.trim().length > 0) {
        return part.value
    }

    return null
}

function normalizeMessageContent(content: unknown): string {
    if (typeof content === 'string') {
        return content
    }

    if (Array.isArray(content)) {
        const extractedTextParts = content
            .map(extractTextFromMessagePart)
            .filter((part): part is string => part !== null)

        if (extractedTextParts.length > 0) {
            return extractedTextParts.join('\n\n')
        }
    }

    return JSON.stringify(content)
}

function extractConversationMessage(rawMessage: RawMessage): { role: ConversationRole; content: string } {
    const normalizedMessageRole = normalizeRole(rawMessage.role, InputMessageRole.User)
    const enumMap: Partial<Record<string, ConversationRole>> = {
        [InputMessageRole.User]: InputMessageRole.User,
        [InputMessageRole.Assistant]: InputMessageRole.Assistant,
    }
    const enumRole: ConversationRole | undefined = enumMap[normalizedMessageRole]

    return {
        role: enumRole ?? InputMessageRole.User,
        content: normalizeMessageContent(rawMessage.content),
    }
}

export const llmPlaygroundPromptsLogic = kea<llmPlaygroundPromptsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'playground', 'llmPlaygroundPromptsLogic']),

    actions({
        addPromptConfig: (sourcePromptId?: string) => ({ sourcePromptId, newPromptId: uuid() }),
        removePromptConfig: (promptId: string) => ({ promptId }),
        setActivePromptId: (promptId: string | null) => ({ promptId }),
        setPromptConfigs: (promptConfigs: PromptConfig[]) => ({ promptConfigs }),
        setModel: (model: string, providerKeyId?: string, promptId?: string) => ({ model, providerKeyId, promptId }),
        setSystemPrompt: (systemPrompt: string, promptId?: string) => ({ systemPrompt, promptId }),
        setMaxTokens: (maxTokens: number | null, promptId?: string) => ({ maxTokens, promptId }),
        setThinking: (thinking: boolean, promptId?: string) => ({ thinking, promptId }),
        setReasoningLevel: (reasoningLevel: ReasoningLevel, promptId?: string) => ({ reasoningLevel, promptId }),
        setTools: (tools: Record<string, unknown>[] | null, promptId?: string) => ({ tools, promptId }),
        clearConversation: (promptId?: string) => ({ promptId }),
        setMessages: (messages: Message[], promptId?: string) => ({ messages, promptId }),
        deleteMessage: (index: number, promptId?: string) => ({ index, promptId }),
        addMessage: (message?: Partial<Message>, promptId?: string) => ({ message, promptId }),
        updateMessage: (index: number, payload: Partial<Message>, promptId?: string) => ({ index, payload, promptId }),
        setupPlaygroundFromEvent: (payload: PlaygroundSetupPayload) => ({ payload }),
        setLocalToolsJson: (json: string | null, promptId?: string) => ({ json, promptId }),
        clearPendingTargetModel: true,
        setEditModal: (
            target: { type: 'tools' | 'system' | 'message'; promptId: string; messageIndex?: number } | null
        ) => ({ target }),
        toggleCollapsed: (key: string) => ({ key }),
        setToolsJsonError: (promptId: string, error: string | null) => ({ promptId, error }),
    }),

    reducers({
        promptConfigs: [
            [INITIAL_PROMPT] as PromptConfig[],
            {
                setPromptConfigs: (_: PromptConfig[], { promptConfigs }: { promptConfigs: PromptConfig[] }) =>
                    promptConfigs.length > 0 ? promptConfigs : [createPromptConfig({ id: INITIAL_PROMPT.id })],
                addPromptConfig: (
                    state: PromptConfig[],
                    { sourcePromptId, newPromptId }: { sourcePromptId?: string; newPromptId: string }
                ) => {
                    const sourcePrompt = state.find((prompt) => prompt.id === sourcePromptId) ?? state[state.length - 1]
                    return [...state, createPromptConfig({ ...sourcePrompt, id: newPromptId })]
                },
                removePromptConfig: (state: PromptConfig[], { promptId }: { promptId: string }) => {
                    if (state.length <= 1) {
                        return state
                    }
                    const nextState = state.filter((prompt) => prompt.id !== promptId)
                    return nextState.length > 0 ? nextState : [createPromptConfig()]
                },
                setModel: (
                    state: PromptConfig[],
                    { model, providerKeyId, promptId }: { model: string; providerKeyId?: string; promptId?: string }
                ) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({
                        ...prompt,
                        model,
                        selectedProviderKeyId: providerKeyId ?? null,
                    })),
                setSystemPrompt: (
                    state: PromptConfig[],
                    { systemPrompt, promptId }: { systemPrompt: string; promptId?: string }
                ) => updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, systemPrompt })),
                setMaxTokens: (
                    state: PromptConfig[],
                    { maxTokens, promptId }: { maxTokens: number | null; promptId?: string }
                ) => updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, maxTokens })),
                setThinking: (
                    state: PromptConfig[],
                    { thinking, promptId }: { thinking: boolean; promptId?: string }
                ) => updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, thinking })),
                setReasoningLevel: (
                    state: PromptConfig[],
                    { reasoningLevel, promptId }: { reasoningLevel: ReasoningLevel; promptId?: string }
                ) => updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, reasoningLevel })),
                setTools: (
                    state: PromptConfig[],
                    { tools, promptId }: { tools: Record<string, unknown>[] | null; promptId?: string }
                ) => updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, tools })),
                clearConversation: (state: PromptConfig[], { promptId }: { promptId?: string }) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, messages: [] })),
                setMessages: (
                    state: PromptConfig[],
                    { messages, promptId }: { messages: Message[]; promptId?: string }
                ) => updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, messages })),
                deleteMessage: (state: PromptConfig[], { index, promptId }: { index: number; promptId?: string }) =>
                    updatePromptConfigs(state, promptId, (prompt) => {
                        if (index < 0 || index >= prompt.messages.length) {
                            return prompt
                        }
                        return { ...prompt, messages: prompt.messages.filter((_, i) => i !== index) }
                    }),
                addMessage: (
                    state: PromptConfig[],
                    { message, promptId }: { message?: Partial<Message>; promptId?: string }
                ) =>
                    updatePromptConfigs(state, promptId, (prompt) => {
                        const defaultMessage: Message = { role: 'user', content: '' }
                        return { ...prompt, messages: [...prompt.messages, { ...defaultMessage, ...message }] }
                    }),
                updateMessage: (
                    state: PromptConfig[],
                    { index, payload, promptId }: { index: number; payload: Partial<Message>; promptId?: string }
                ) =>
                    updatePromptConfigs(state, promptId, (prompt) => {
                        if (index < 0 || index >= prompt.messages.length) {
                            return prompt
                        }
                        const newMessages = [...prompt.messages]
                        newMessages[index] = { ...newMessages[index], ...payload }
                        return { ...prompt, messages: newMessages }
                    }),
                setupPlaygroundFromEvent: (state: PromptConfig[], { payload }: { payload: PlaygroundSetupPayload }) => {
                    const targetPrompt = state[0] ?? createPromptConfig({ id: INITIAL_PROMPT.id })
                    const normalizedModel = payload.model ?? targetPrompt.model
                    return [
                        {
                            ...targetPrompt,
                            model: normalizedModel,
                        },
                    ]
                },
            },
        ],
        activePromptId: [
            INITIAL_PROMPT.id as string | null,
            {
                addPromptConfig: (_: string | null, { newPromptId }: { newPromptId: string }) => newPromptId,
                setActivePromptId: (_: string | null, { promptId }: { promptId: string | null }) => promptId,
                removePromptConfig: (state: string | null, { promptId }: { promptId: string }) =>
                    state === promptId ? null : state,
                setupPlaygroundFromEvent: () => INITIAL_PROMPT.id,
            },
        ],
        localToolsJsonByPromptId: [
            {} as Record<string, string | null>,
            {
                setLocalToolsJson: (
                    state: Record<string, string | null>,
                    { json, promptId }: { json: string | null; promptId?: string }
                ) => {
                    if (!promptId) {
                        return state
                    }
                    return { ...state, [promptId]: json }
                },
                setTools: (state: Record<string, string | null>, { promptId }: { promptId?: string }) => {
                    if (!promptId) {
                        return state
                    }
                    return { ...state, [promptId]: null }
                },
                removePromptConfig: (state: Record<string, string | null>, { promptId }: { promptId: string }) => {
                    const { [promptId]: _, ...rest } = state
                    return rest
                },
            },
        ],
        pendingTargetModel: [
            null as string | null,
            {
                setupPlaygroundFromEvent: (_: string | null, { payload }: { payload: { model?: string } }) =>
                    payload.model ?? null,
                clearPendingTargetModel: () => null,
            },
        ],
        pendingTargetProvider: [
            null as string | null,
            {
                setupPlaygroundFromEvent: (_: string | null, { payload }: { payload: { provider?: string } }) =>
                    normalizeLLMProvider(payload.provider),
                clearPendingTargetModel: () => null,
            },
        ],
        pendingTargetIsTrace: [
            false as boolean,
            {
                setupPlaygroundFromEvent: (
                    _: boolean,
                    { payload }: { payload: { model?: string; provider?: string } }
                ) => isTraceLikeSelection(payload.model, payload.provider),
                clearPendingTargetModel: () => false,
            },
        ],
        editModal: [
            null as { type: 'tools' | 'system' | 'message'; promptId: string; messageIndex?: number } | null,
            {
                setEditModal: (
                    _: { type: string; promptId: string; messageIndex?: number } | null,
                    {
                        target,
                    }: {
                        target: { type: 'tools' | 'system' | 'message'; promptId: string; messageIndex?: number } | null
                    }
                ) => target,
            },
        ],
        collapsedSections: [
            {} as Record<string, boolean>,
            {
                toggleCollapsed: (state: Record<string, boolean>, { key }: { key: string }) => ({
                    ...state,
                    [key]: !state[key],
                }),
            },
        ],
        toolsJsonErrorByPromptId: [
            {} as Record<string, string | null>,
            {
                setToolsJsonError: (
                    state: Record<string, string | null>,
                    { promptId, error }: { promptId: string; error: string | null }
                ) => ({ ...state, [promptId]: error }),
                removePromptConfig: (state: Record<string, string | null>, { promptId }: { promptId: string }) => {
                    const { [promptId]: _, ...rest } = state
                    return rest
                },
            },
        ],
    }),

    selectors({
        activePromptConfig: [
            (s) => [s.promptConfigs, s.activePromptId],
            (promptConfigs: PromptConfig[], activePromptId: string | null): PromptConfig => {
                return (
                    promptConfigs.find((prompt) => prompt.id === activePromptId) ??
                    promptConfigs[0] ??
                    createPromptConfig({ id: INITIAL_PROMPT.id })
                )
            },
        ],
        model: [(s) => [s.activePromptConfig], (activePromptConfig: PromptConfig): string => activePromptConfig.model],
        selectedProviderKeyId: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): string | null => activePromptConfig.selectedProviderKeyId,
        ],
        systemPrompt: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): string => activePromptConfig.systemPrompt,
        ],
        maxTokens: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): number | null => activePromptConfig.maxTokens,
        ],
        thinking: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): boolean => activePromptConfig.thinking,
        ],
        reasoningLevel: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): ReasoningLevel => activePromptConfig.reasoningLevel,
        ],
        tools: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): Record<string, unknown>[] | null => activePromptConfig.tools,
        ],
        messages: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): Message[] => activePromptConfig.messages,
        ],
        hasRunnablePrompts: [
            (s) => [s.promptConfigs],
            (promptConfigs: PromptConfig[]): boolean =>
                promptConfigs.some((prompt) => prompt.messages.some((message) => message.content.trim().length > 0)),
        ],
    }),

    listeners(({ actions, values }) => ({
        removePromptConfig: ({ promptId }) => {
            if (values.promptConfigs.length === 0) {
                actions.setPromptConfigs([createPromptConfig({ id: INITIAL_PROMPT.id })])
                actions.setActivePromptId(INITIAL_PROMPT.id)
                return
            }

            if (values.activePromptId === null || values.activePromptId === promptId) {
                actions.setActivePromptId(values.promptConfigs[0]?.id ?? null)
            }
        },

        setupPlaygroundFromEvent: ({ payload }) => {
            const { input, tools } = payload
            const currentPrompt = values.promptConfigs[0] ?? createPromptConfig({ id: INITIAL_PROMPT.id })
            const promptId = currentPrompt.id

            if (tools) {
                actions.setTools(tools, promptId)
            }

            let systemPromptContent: string | undefined = undefined
            let conversationMessages: Message[] = []
            let initialUserPrompt: string | undefined = undefined

            if (input) {
                try {
                    if (Array.isArray(input) && input.every((msg) => msg.role && msg.content)) {
                        const systemContents = input
                            .filter((msg) => msg.role === 'system')
                            .map((msg) => msg.content)
                            .filter(
                                (content): content is string => typeof content === 'string' && content.trim().length > 0
                            )

                        if (systemContents.length > 0) {
                            systemPromptContent = systemContents.join('\n\n')
                        }

                        conversationMessages = input
                            .filter((msg: RawMessage) => msg.role !== 'system')
                            .map((msg: RawMessage) => extractConversationMessage(msg))
                    } else if (typeof input === 'string') {
                        initialUserPrompt = input
                    } else if (isObject(input)) {
                        if (typeof input.content === 'string') {
                            initialUserPrompt = input.content
                        } else if (input.content && typeof input.content !== 'string') {
                            initialUserPrompt = JSON.stringify(input.content, null, 2)
                        } else {
                            initialUserPrompt = JSON.stringify(input, null, 2)
                        }
                    }
                } catch (e) {
                    console.error('Error processing input for playground:', e)
                    initialUserPrompt = String(input)
                    conversationMessages = []
                }
            }

            actions.setSystemPrompt(systemPromptContent ?? DEFAULT_SYSTEM_PROMPT, promptId)

            if (initialUserPrompt) {
                conversationMessages.unshift({ role: 'user', content: initialUserPrompt })
            }

            actions.setMessages(conversationMessages, promptId)
            actions.setActivePromptId(promptId)
            router.actions.push(urls.llmAnalyticsPlayground())
        },
    })),
])
