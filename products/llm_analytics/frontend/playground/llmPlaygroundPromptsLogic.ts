import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { isObject, uuid } from 'lib/utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { llmEvaluationLogic } from '../evaluations/llmEvaluationLogic'
import type { EvaluationConfig } from '../evaluations/types'
import { getApiErrorDetail, llmPromptLogic } from '../prompts/llmPromptLogic'
import { normalizeLLMProvider } from '../settings/llmProviderKeysLogic'
import { normalizeRole, safeStringify } from '../utils'
import type { llmPlaygroundPromptsLogicType } from './llmPlaygroundPromptsLogicType'
import { isTraceLikeSelection } from './playgroundModelMatching'

const SOURCE_PARAM_KEYS = ['source_prompt_name', 'source_prompt_version', 'source_evaluation_id'] as const

/** Strip all source-linking URL params, returning only the unrelated params. */
export function cleanSourceSearchParams(searchParams: Record<string, any>): Record<string, any> {
    const clean = { ...searchParams }
    for (const key of SOURCE_PARAM_KEYS) {
        delete clean[key]
    }
    return clean
}

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
    temperature: number | null
    topP: number | null
    thinking: boolean
    reasoningLevel: ReasoningLevel
    tools: Record<string, unknown>[] | null
    sourceType: 'prompt' | 'evaluation' | null
    sourcePromptName: string | null
    sourcePromptVersion: number | null
    sourceEvaluationId: string | null
    sourceEvaluationName: string | null
    messages: Message[]
}

export interface PlaygroundSetupPayload {
    model?: string
    provider?: string
    providerKeyId?: string
    systemPrompt?: string
    sourceType?: 'prompt' | 'evaluation'
    sourcePromptName?: string
    sourcePromptVersion?: number
    sourceEvaluationId?: string
    input?: unknown
    output?: unknown
    tools?: Record<string, unknown>[]
}

export const DEFAULT_SYSTEM_PROMPT = 'You are a helpful AI assistant.'

/**
 * Module-level store for a pending playground setup payload. External callers (trace scene,
 * conversation display) write here before navigating to the playground, so the tab-keyed
 * instance can pick it up in urlToAction and run setupPlaygroundFromEvent on itself.
 *
 * This avoids the fragile "transfer from default instance" pattern, which breaks when the
 * source component unmounts before the playground's urlToAction fires.
 */
let pendingPlaygroundSetup: PlaygroundSetupPayload | null = null

/** Queue a setup payload and navigate to the playground. */
export function openInPlayground(payload: PlaygroundSetupPayload): void {
    pendingPlaygroundSetup = payload
    router.actions.push(urls.llmAnalyticsPlayground())
}

function consumePendingPlaygroundSetup(): PlaygroundSetupPayload | null {
    const payload = pendingPlaygroundSetup
    pendingPlaygroundSetup = null
    return payload
}

/**
 * Returns a human-readable label for the linked source, e.g. `prompt "my-prompt"` or `evaluation "my-eval"`.
 * Returns null when no source is linked.
 */
export function getLinkedSourceLabel(source: {
    type: 'prompt' | 'evaluation' | null
    promptName: string | null
    promptVersion?: number | null
    evaluationId: string | null
    evaluationName: string | null
}): string | null {
    if (source.type === 'prompt') {
        if (!source.promptName) {
            return null
        }
        const versionSuffix = source.promptVersion ? ` v${source.promptVersion}` : ''
        return `prompt "${source.promptName}"${versionSuffix}`
    }
    if (source.type === 'evaluation') {
        if (source.evaluationName) {
            return `evaluation "${source.evaluationName}"`
        }
        if (source.evaluationId) {
            return `evaluation ${source.evaluationId.slice(0, 8)}`
        }
    }
    return null
}

export function createPromptConfig(partial: Partial<PromptConfig> = {}): PromptConfig {
    return {
        id: partial.id ?? uuid(),
        model: partial.model ?? '',
        selectedProviderKeyId: partial.selectedProviderKeyId ?? null,
        systemPrompt: partial.systemPrompt ?? DEFAULT_SYSTEM_PROMPT,
        maxTokens: partial.maxTokens ?? null,
        temperature: partial.temperature ?? null,
        topP: partial.topP ?? null,
        thinking: partial.thinking ?? false,
        reasoningLevel: partial.reasoningLevel ?? 'medium',
        tools: partial.tools ?? null,
        sourceType: partial.sourceType ?? null,
        sourcePromptName: partial.sourcePromptName ?? null,
        sourcePromptVersion: partial.sourcePromptVersion ?? null,
        sourceEvaluationId: partial.sourceEvaluationId ?? null,
        sourceEvaluationName: partial.sourceEvaluationName ?? null,
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
    tool_calls?: unknown
    tool_call_id?: unknown
    type?: string
}

type ConversationRole = 'user' | 'assistant'

enum InputMessageRole {
    User = 'user',
    Assistant = 'assistant',
    AI = 'ai',
    Model = 'model',
}

// Formats a typed content block (one with a `type` field) into readable text.
// Returns null for unrecognized types so callers can fall through.
function formatContentBlock(part: Record<string, unknown>): string | null {
    const type = part.type

    if (type === 'text' || type === 'output_text' || type === 'input_text') {
        const text = part.text
        return typeof text === 'string' && text.trim().length > 0 ? text : null
    }

    // Anthropic: { type: 'tool_use', id, name, input }
    if (type === 'tool_use') {
        const name = part.name ?? 'unknown'
        const input = part.input !== undefined ? safeStringify(part.input) : '{}'
        return `[Tool call: ${name}]\n${input}`
    }

    // Anthropic: { type: 'tool_result', tool_use_id, content }
    if (type === 'tool_result') {
        const toolId = typeof part.tool_use_id === 'string' ? part.tool_use_id : null
        const content = typeof part.content === 'string' ? part.content : safeStringify(part.content)
        const header = toolId ? `[Tool result for ${toolId}]` : '[Tool result]'
        return `${header}\n${content}`
    }

    // OpenAI Responses API: { type: 'function_call', name, call_id, arguments }
    if (type === 'function_call') {
        const name = part.name ?? 'unknown'
        const args = typeof part.arguments === 'string' ? part.arguments : safeStringify(part.arguments)
        return `[Function call: ${name}]\n${args}`
    }

    // OpenAI Responses API: { type: 'function_call_output', call_id, output }
    if (type === 'function_call_output') {
        const callId = typeof part.call_id === 'string' ? part.call_id : null
        const output = typeof part.output === 'string' ? part.output : safeStringify(part.output)
        const header = callId ? `[Function output for ${callId}]` : '[Function output]'
        return `${header}\n${output}`
    }

    return null
}

// Formats OpenAI-style top-level tool_calls arrays into readable text
function formatToolCallsForPlayground(toolCalls: unknown): string {
    if (!Array.isArray(toolCalls) || toolCalls.length === 0) {
        return ''
    }
    return toolCalls
        .map((tc) => {
            if (!isObject(tc)) {
                return safeStringify(tc)
            }
            const fn = isObject(tc.function) ? tc.function : tc
            const name = fn.name ?? 'unknown'
            const args = fn.arguments ?? '{}'
            const argsStr = typeof args === 'string' ? args : safeStringify(args)
            return `[Tool call: ${name}]\n${argsStr}`
        })
        .join('\n\n')
}

function extractTextFromMessagePart(part: unknown): string | null {
    if (!isObject(part)) {
        return null
    }

    // Typed content blocks are handled by formatContentBlock, which checks
    // `type` before any generic field extraction — preventing e.g. a
    // tool_result's `.content` from being misidentified as plain text.
    if (typeof part.type === 'string') {
        return formatContentBlock(part)
    }

    // Untyped objects: try common text field names
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
    if (content === null || content === undefined) {
        return ''
    }

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

    return safeStringify(content)
}

// Safety cap on recursion depth in flattenOutputMessages. Trace payloads can't have true cycles
// (they come from `JSON.parse`), but deeply nested `{ message: { message: … } }` chains or arrays
// of arrays could run the stack down — bail early and hand back an empty list instead.
const MAX_OUTPUT_FLATTEN_DEPTH = 100

// Flattens a raw generation output (string, single message, message array, or an
// OpenAI/LiteLLM-style { choices: [...] } wrapper) into a list of RawMessage entries
// without splitting structured content blocks — unlike `normalizeMessages` from utils,
// which fans out tool_use/tool_result blocks into separate display bubbles.
function flattenOutputMessages(output: unknown, depth: number = 0): RawMessage[] {
    if (output == null || depth > MAX_OUTPUT_FLATTEN_DEPTH) {
        return []
    }

    if (typeof output === 'string') {
        return [{ role: InputMessageRole.Assistant, content: output }]
    }

    if (Array.isArray(output)) {
        return output.flatMap((item) => flattenOutputMessages(item, depth + 1))
    }

    if (isObject(output)) {
        if (Array.isArray(output.choices)) {
            return output.choices.flatMap((item) => flattenOutputMessages(item, depth + 1))
        }
        if (isObject(output.message)) {
            return flattenOutputMessages(output.message, depth + 1)
        }
        // OpenAI Responses API top-level function_call / function_call_output items have no role.
        // Convert them to synthetic RawMessages so extractConversationMessage can format them.
        // Preserve `type` so isToolResultMessage can still identify function_call_output and fold
        // it into the preceding assistant turn rather than emitting a standalone user bubble.
        if (output.type === 'function_call' || output.type === 'function_call_output') {
            return [
                {
                    role: output.type === 'function_call_output' ? InputMessageRole.User : InputMessageRole.Assistant,
                    content: formatContentBlock(output) ?? '',
                    tool_call_id: output.call_id,
                    type: String(output.type),
                },
            ]
        }
        return [
            {
                role: typeof output.role === 'string' ? output.role : InputMessageRole.Assistant,
                content: output.content,
                tool_calls: output.tool_calls,
                tool_call_id: output.tool_call_id,
            },
        ]
    }

    return []
}

function extractConversationMessage(rawMessage: RawMessage): { role: ConversationRole; content: string } {
    // OpenAI Responses API sends function_call / function_call_output items at the top level of the
    // conversation array with no `role`. Route them through formatContentBlock so they get the same
    // `[Function call: name]` / `[Function output for id]` treatment as typed content blocks.
    const rawAsBlock = rawMessage as unknown as Record<string, unknown>
    const topLevelType = rawMessage.type
    if (
        typeof rawMessage.role !== 'string' &&
        (topLevelType === 'function_call' || topLevelType === 'function_call_output')
    ) {
        const formatted = formatContentBlock(rawAsBlock) ?? ''
        const role: ConversationRole =
            topLevelType === 'function_call_output' ? InputMessageRole.User : InputMessageRole.Assistant
        return { role, content: formatted }
    }

    const normalizedMessageRole = normalizeRole(rawMessage.role, InputMessageRole.User)
    const enumMap: Partial<Record<string, ConversationRole>> = {
        [InputMessageRole.User]: InputMessageRole.User,
        [InputMessageRole.Assistant]: InputMessageRole.Assistant,
    }
    const enumRole: ConversationRole | undefined = enumMap[normalizedMessageRole]

    let content = normalizeMessageContent(rawMessage.content)

    // Tool-role messages collapse into a user turn since the playground only renders user/assistant.
    // Prefix with `[Tool result …]` so the origin is preserved — in practice the caller will merge
    // this into the preceding assistant turn via `appendRawMessage`, but the prefix is kept for the
    // rare case where a tool result has no preceding assistant (e.g. a broken trace).
    if (normalizedMessageRole === 'tool') {
        const toolId = typeof rawMessage.tool_call_id === 'string' ? rawMessage.tool_call_id : null
        const header = toolId ? `[Tool result for ${toolId}]` : '[Tool result]'
        content = `${header}\n${content}`
    }

    // Append top-level tool_calls (OpenAI format) when present
    const toolCallsText = formatToolCallsForPlayground(rawMessage.tool_calls)
    if (toolCallsText) {
        content = content ? `${content}\n\n${toolCallsText}` : toolCallsText
    }

    return {
        role: enumRole ?? InputMessageRole.User,
        content,
    }
}

// Detects messages whose entire purpose is carrying a tool response — OpenAI `role: 'tool'` or an
// Anthropic-style `role: 'user'` message whose content is a pure `tool_result` / `function_call_output`
// block. Such messages don't represent a real user turn and should be folded into the preceding
// assistant turn rather than rendered as standalone user bubbles in the playground.
function isToolResultMessage(raw: RawMessage): boolean {
    if (normalizeRole(raw.role, '') === 'tool') {
        return true
    }
    // OpenAI Responses API top-level function_call_output item (no role)
    if (raw.type === 'function_call_output') {
        return true
    }
    if (Array.isArray(raw.content) && raw.content.length > 0) {
        return raw.content.every((c) => isObject(c) && (c.type === 'tool_result' || c.type === 'function_call_output'))
    }
    return false
}

// Appends a raw message to a running conversation, merging tool-result messages into the previous
// assistant turn rather than emitting a separate user bubble. This keeps the playground's display
// in line with how tool calls/results conceptually bind together, without requiring a dedicated
// tool role in the playground's Message model.
function appendRawMessage(conversation: Message[], raw: RawMessage): void {
    const extracted = extractConversationMessage(raw)
    const prev = conversation[conversation.length - 1]

    if (isToolResultMessage(raw) && prev?.role === InputMessageRole.Assistant) {
        prev.content = prev.content ? `${prev.content}\n\n${extracted.content}` : extracted.content
        return
    }

    conversation.push(extracted)
}

export interface LLMPlaygroundPromptsLogicProps {
    tabId?: string
}

export const llmPlaygroundPromptsLogic = kea<llmPlaygroundPromptsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'playground', 'llmPlaygroundPromptsLogic']),
    props({} as LLMPlaygroundPromptsLogicProps),
    key((props) => props.tabId ?? 'default'),

    actions({
        addPromptConfig: (sourcePromptId?: string) => ({ sourcePromptId, newPromptId: uuid() }),
        removePromptConfig: (promptId: string) => ({ promptId }),
        setActivePromptId: (promptId: string | null) => ({ promptId }),
        setPromptConfigs: (promptConfigs: PromptConfig[]) => ({ promptConfigs }),
        setModel: (model: string, providerKeyId?: string, promptId?: string) => ({ model, providerKeyId, promptId }),
        setSystemPrompt: (systemPrompt: string, promptId?: string) => ({ systemPrompt, promptId }),
        setMaxTokens: (maxTokens: number | null, promptId?: string) => ({ maxTokens, promptId }),
        setTemperature: (temperature: number | null, promptId?: string) => ({ temperature, promptId }),
        setTopP: (topP: number | null, promptId?: string) => ({ topP, promptId }),
        setThinking: (thinking: boolean, promptId?: string) => ({ thinking, promptId }),
        setReasoningLevel: (reasoningLevel: ReasoningLevel, promptId?: string) => ({ reasoningLevel, promptId }),
        setTools: (tools: Record<string, unknown>[] | null, promptId?: string) => ({ tools, promptId }),
        clearConversation: (promptId?: string) => ({ promptId }),
        setMessages: (messages: Message[], promptId?: string) => ({ messages, promptId }),
        deleteMessage: (index: number, promptId?: string) => ({ index, promptId }),
        addMessage: (message?: Partial<Message>, promptId?: string) => ({ message, promptId }),
        addResultToConversation: (response: string, promptId?: string) => ({ response, promptId }),
        updateMessage: (index: number, payload: Partial<Message>, promptId?: string) => ({ index, payload, promptId }),
        clearLinkedSource: true,
        setSourceNames: (promptName: string | null, evaluationName: string | null, promptId?: string) => ({
            promptName,
            evaluationName,
            promptId,
        }),
        setupPlaygroundFromEvent: (payload: PlaygroundSetupPayload) => ({ payload }),
        setLocalToolsJson: (json: string | null, promptId?: string) => ({ json, promptId }),
        clearPendingTargetModel: true,
        setEditModal: (
            target: { type: 'tools' | 'system' | 'message'; promptId: string; messageIndex?: number } | null
        ) => ({ target }),
        toggleCollapsed: (key: string) => ({ key }),
        setToolsJsonError: (promptId: string, error: string | null) => ({ promptId, error }),
        setSourceSetupLoading: (isLoading: boolean) => ({ isLoading }),
        saveToLinkedPrompt: (promptId: string) => ({ promptId }),
        saveToLinkedEvaluation: (
            promptId: string,
            modelConfig: { model: string; provider: string; provider_key_id: string | null } | null
        ) => ({ promptId, modelConfig }),
        saveAsNewPrompt: (promptId: string, name: string) => ({ promptId, name }),
        saveAsNewEvaluation: (
            promptId: string,
            name: string,
            modelConfig: { model: string; provider: string; provider_key_id: string | null } | null
        ) => ({ promptId, name, modelConfig }),
        saveComplete: true,
        resetPlayground: true,
    }),

    reducers({
        promptConfigs: [
            [INITIAL_PROMPT] as PromptConfig[],
            {
                resetPlayground: () => [createPromptConfig()],
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
                setTemperature: (
                    state: PromptConfig[],
                    { temperature, promptId }: { temperature: number | null; promptId?: string }
                ) => updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, temperature })),
                setTopP: (state: PromptConfig[], { topP, promptId }: { topP: number | null; promptId?: string }) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({ ...prompt, topP })),
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
                addResultToConversation: (
                    state: PromptConfig[],
                    { response, promptId }: { response: string; promptId?: string }
                ) => {
                    if (!response.trim()) {
                        return state
                    }
                    return updatePromptConfigs(state, promptId, (prompt) => ({
                        ...prompt,
                        messages: [
                            ...prompt.messages,
                            { role: 'assistant', content: response },
                            { role: 'user', content: '' },
                        ],
                    }))
                },
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
                clearLinkedSource: (state: PromptConfig[]) =>
                    updatePromptConfigs(state, state[0]?.id, (prompt) => ({
                        ...prompt,
                        sourceType: null,
                        sourcePromptName: null,
                        sourcePromptVersion: null,
                        sourceEvaluationId: null,
                        sourceEvaluationName: null,
                    })),
                setSourceNames: (
                    state: PromptConfig[],
                    {
                        promptName,
                        evaluationName,
                        promptId,
                    }: { promptName: string | null; evaluationName: string | null; promptId?: string }
                ) =>
                    updatePromptConfigs(state, promptId, (prompt) => ({
                        ...prompt,
                        sourcePromptName: promptName,
                        sourceEvaluationName: evaluationName,
                    })),
                setupPlaygroundFromEvent: (state: PromptConfig[], { payload }: { payload: PlaygroundSetupPayload }) => {
                    const targetPrompt = state[0] ?? createPromptConfig({ id: INITIAL_PROMPT.id })
                    const normalizedModel = payload.model ?? targetPrompt.model
                    return [
                        {
                            ...targetPrompt,
                            model: normalizedModel,
                            selectedProviderKeyId: payload.providerKeyId ?? null,
                            sourceType: payload.sourceType ?? null,
                            sourcePromptName: payload.sourcePromptName ?? null,
                            sourcePromptVersion: payload.sourcePromptVersion ?? null,
                            sourceEvaluationId: payload.sourceEvaluationId ?? null,
                            sourceEvaluationName: null,
                        },
                    ]
                },
            },
        ],
        activePromptId: [
            INITIAL_PROMPT.id as string | null,
            {
                resetPlayground: () => null,
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
                resetPlayground: () => ({}),
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
                resetPlayground: () => null,
                setupPlaygroundFromEvent: (_: string | null, { payload }: { payload: { model?: string } }) =>
                    payload.model ?? null,
                clearPendingTargetModel: () => null,
            },
        ],
        pendingTargetProvider: [
            null as string | null,
            {
                resetPlayground: () => null,
                setupPlaygroundFromEvent: (_: string | null, { payload }: { payload: { provider?: string } }) =>
                    normalizeLLMProvider(payload.provider),
                clearPendingTargetModel: () => null,
            },
        ],
        pendingTargetIsTrace: [
            false as boolean,
            {
                resetPlayground: () => false,
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
                resetPlayground: () => null,
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
                resetPlayground: () => ({}),
                toggleCollapsed: (state: Record<string, boolean>, { key }: { key: string }) => ({
                    ...state,
                    [key]: !state[key],
                }),
            },
        ],
        toolsJsonErrorByPromptId: [
            {} as Record<string, string | null>,
            {
                resetPlayground: () => ({}),
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
        sourceSetupLoading: [
            false as boolean,
            {
                setSourceSetupLoading: (_: boolean, { isLoading }: { isLoading: boolean }) => isLoading,
            },
        ],
        saving: [
            false as boolean,
            {
                saveToLinkedPrompt: () => true,
                saveToLinkedEvaluation: () => true,
                saveAsNewPrompt: () => true,
                saveAsNewEvaluation: () => true,
                saveComplete: () => false,
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
        temperature: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): number | null => activePromptConfig.temperature,
        ],
        topP: [
            (s) => [s.activePromptConfig],
            (activePromptConfig: PromptConfig): number | null => activePromptConfig.topP,
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
        linkedSource: [
            (s) => [s.promptConfigs],
            (
                promptConfigs: PromptConfig[]
            ): {
                type: 'prompt' | 'evaluation' | null
                promptName: string | null
                promptVersion: number | null
                evaluationId: string | null
                evaluationName: string | null
            } => {
                const first = promptConfigs[0]
                if (!first) {
                    return {
                        type: null,
                        promptName: null,
                        promptVersion: null,
                        evaluationId: null,
                        evaluationName: null,
                    }
                }
                return {
                    type: first.sourceType,
                    promptName: first.sourcePromptName,
                    promptVersion: first.sourcePromptVersion,
                    evaluationId: first.sourceEvaluationId,
                    evaluationName: first.sourceEvaluationName,
                }
            },
        ],
        hasRunnablePrompts: [
            (s) => [s.promptConfigs],
            (promptConfigs: PromptConfig[]): boolean =>
                promptConfigs.some((prompt) => prompt.messages.some((message) => message.content.trim().length > 0)),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        resetPlayground: () => {
            posthog.capture('llma playground reset')
            const activeTabId = sceneLogic.findMounted()?.values.activeTabId
            const isActiveTab = !activeTabId || activeTabId === props.tabId
            if (isActiveTab) {
                router.actions.replace(
                    combineUrl(urls.llmAnalyticsPlayground(), cleanSourceSearchParams(router.values.searchParams)).url
                )
            }
        },
        addPromptConfig: () => {
            // New total after adding — listeners run post-reducer
            posthog.capture('llma playground prompt config added', {
                prompt_count: values.promptConfigs.length,
            })
        },
        removePromptConfig: ({ promptId }) => {
            posthog.capture('llma playground prompt config removed', {
                prompt_count: values.promptConfigs.length,
            })
            if (values.promptConfigs.length === 0) {
                actions.setPromptConfigs([createPromptConfig({ id: INITIAL_PROMPT.id })])
                actions.setActivePromptId(INITIAL_PROMPT.id)
                return
            }

            if (values.activePromptId === null || values.activePromptId === promptId) {
                actions.setActivePromptId(values.promptConfigs[0]?.id ?? null)
            }
        },

        addMessage: () => {
            posthog.capture('llma playground message added', {
                message_count: values.activePromptConfig?.messages.length ?? 0,
            })
        },
        deleteMessage: () => {
            posthog.capture('llma playground message removed', {
                message_count: values.activePromptConfig?.messages.length ?? 0,
            })
        },
        setTools: ({ tools }) => {
            posthog.capture('llma playground tools configured', {
                action: tools ? 'set' : 'clear',
                tool_count: tools?.length ?? 0,
            })
        },

        setupPlaygroundFromEvent: async ({ payload }) => {
            const sourceType = payload.sourceType ?? (payload.input ? 'trace' : null)
            posthog.capture('llma playground opened from source', {
                source_type: sourceType ?? 'unknown',
            })
            actions.setSourceSetupLoading(true)
            const { input, tools, systemPrompt } = payload
            const currentPrompt = values.promptConfigs[0] ?? createPromptConfig({ id: INITIAL_PROMPT.id })
            const promptId = currentPrompt.id

            const finishSourceSetup = (sourceParam: Record<string, string>): void => {
                actions.setMessages([], promptId)
                actions.setActivePromptId(promptId)
                const cleanParams = cleanSourceSearchParams(router.values.searchParams)
                router.actions.push(combineUrl(urls.llmAnalyticsPlayground(), { ...cleanParams, ...sourceParam }).url)
            }

            try {
                if (payload.sourcePromptName) {
                    try {
                        const versionParam = payload.sourcePromptVersion
                            ? { version: payload.sourcePromptVersion }
                            : undefined
                        const fetchedPrompt = await api.llmPrompts.getByName(payload.sourcePromptName, versionParam)
                        actions.setSystemPrompt(fetchedPrompt.prompt || DEFAULT_SYSTEM_PROMPT, promptId)
                        actions.setSourceNames(fetchedPrompt.name ?? null, null, promptId)
                        const sourceParams: Record<string, string> = {
                            source_prompt_name: payload.sourcePromptName,
                        }
                        if (payload.sourcePromptVersion) {
                            sourceParams.source_prompt_version = String(payload.sourcePromptVersion)
                        }
                        finishSourceSetup(sourceParams)
                    } catch {
                        lemonToast.error('Error loading prompt for playground')
                    }
                    return
                }

                if (payload.sourceEvaluationId) {
                    try {
                        const teamId = teamLogic.values.currentTeamId
                        if (!teamId) {
                            lemonToast.error('Could not determine team')
                            return
                        }
                        // nosemgrep: prefer-codegen-api
                        const fetchedEvaluation = await api.get<EvaluationConfig>(
                            `/api/environments/${teamId}/evaluations/${payload.sourceEvaluationId}/`
                        )
                        actions.setSourceNames(null, fetchedEvaluation.name ?? null, promptId)
                        if (fetchedEvaluation.evaluation_type === 'llm_judge') {
                            actions.setSystemPrompt(
                                fetchedEvaluation.evaluation_config.prompt || DEFAULT_SYSTEM_PROMPT,
                                promptId
                            )
                            const model = fetchedEvaluation.model_configuration?.model
                            const providerKeyId = fetchedEvaluation.model_configuration?.provider_key_id
                            if (model) {
                                actions.setModel(model, providerKeyId ?? undefined, promptId)
                            }
                        }
                        finishSourceSetup({ source_evaluation_id: payload.sourceEvaluationId })
                    } catch {
                        lemonToast.error('Error loading evaluation for playground')
                    }
                    return
                }

                if (tools) {
                    actions.setTools(tools, promptId)
                }

                let systemPromptContent: string | undefined = undefined
                let conversationMessages: Message[] = []
                let initialUserPrompt: string | undefined = undefined

                if (input) {
                    try {
                        if (
                            Array.isArray(input) &&
                            input.every(
                                (msg) =>
                                    // Standard chat message: must have role + content/tool_calls
                                    (msg.role && (msg.content != null || msg.tool_calls)) ||
                                    // OpenAI Responses API top-level typed items have no role
                                    msg.type === 'function_call' ||
                                    msg.type === 'function_call_output'
                            )
                        ) {
                            const systemContents = input
                                .filter((msg) => msg.role === 'system')
                                .map((msg) => msg.content)
                                .filter(
                                    (content): content is string =>
                                        typeof content === 'string' && content.trim().length > 0
                                )

                            if (systemContents.length > 0) {
                                systemPromptContent = systemContents.join('\n\n')
                            }

                            for (const msg of input as RawMessage[]) {
                                if (msg.role === 'system') {
                                    continue
                                }
                                appendRawMessage(conversationMessages, msg)
                            }
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

                actions.setSystemPrompt(systemPrompt ?? systemPromptContent ?? DEFAULT_SYSTEM_PROMPT, promptId)

                if (initialUserPrompt) {
                    conversationMessages.unshift({ role: 'user', content: initialUserPrompt })
                }

                // Append the generation output as assistant turn(s) so users see the full exchange.
                // `flattenOutputMessages` unwraps LiteLLM/OpenAI `choices` shapes and string outputs,
                // then `appendRawMessage` folds any tool-result messages into the preceding assistant turn.
                if (payload.output != null) {
                    try {
                        for (const msg of flattenOutputMessages(payload.output)) {
                            appendRawMessage(conversationMessages, msg)
                        }
                    } catch (e) {
                        console.error('Error processing output for playground:', e)
                    }
                }

                actions.setMessages(conversationMessages, promptId)
                actions.setActivePromptId(promptId)
            } finally {
                actions.setSourceSetupLoading(false)
            }
        },

        saveToLinkedPrompt: async ({ promptId }) => {
            posthog.capture('llma playground saved to source', { action: 'save_to_linked_prompt' })
            const { linkedSource, promptConfigs } = values
            if (!linkedSource.promptName) {
                lemonToast.error('No linked prompt to save to')
                actions.saveComplete()
                return
            }
            const prompt = promptConfigs.find((p) => p.id === promptId)
            if (!prompt) {
                lemonToast.error('No prompt configuration to save')
                actions.saveComplete()
                return
            }
            try {
                const current = await api.llmPrompts.getByName(linkedSource.promptName)
                await api.llmPrompts.update(linkedSource.promptName, {
                    prompt: prompt.systemPrompt,
                    base_version: current.latest_version,
                })
                const promptName = linkedSource.promptName
                // After saving, the playground is linked to the latest version
                if (linkedSource.promptVersion) {
                    actions.setPromptConfigs(
                        updatePromptConfigs(values.promptConfigs, prompt.id, (p) => ({
                            ...p,
                            sourcePromptVersion: null,
                        }))
                    )
                    const { source_prompt_version: _, ...cleanParams } = router.values.searchParams
                    router.actions.replace(combineUrl(urls.llmAnalyticsPlayground(), cleanParams).url)
                }
                const label = getLinkedSourceLabel(values.linkedSource) ?? 'linked prompt'
                lemonToast.success(`${label.charAt(0).toUpperCase()}${label.slice(1)} updated`, {
                    button: {
                        label: 'View',
                        action: () => router.actions.push(urls.llmAnalyticsPrompt(promptName)),
                    },
                })
                for (const logic of llmPromptLogic.findAllMounted()) {
                    if (logic.props.promptName === promptName) {
                        logic.actions.loadPrompt()
                    }
                }
            } catch (error: unknown) {
                lemonToast.error(getApiErrorDetail(error) || 'Failed to update prompt')
            } finally {
                actions.saveComplete()
            }
        },

        saveToLinkedEvaluation: async ({ promptId, modelConfig }) => {
            posthog.capture('llma playground saved to source', { action: 'save_to_linked_evaluation' })
            const { linkedSource, promptConfigs } = values
            if (!linkedSource.evaluationId) {
                lemonToast.error('No linked evaluation to save to')
                actions.saveComplete()
                return
            }
            const prompt = promptConfigs.find((p) => p.id === promptId)
            if (!prompt) {
                lemonToast.error('No prompt configuration to save')
                actions.saveComplete()
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                lemonToast.error('Could not determine team')
                actions.saveComplete()
                return
            }
            try {
                // nosemgrep: prefer-codegen-api
                await api.update(`/api/environments/${teamId}/evaluations/${linkedSource.evaluationId}/`, {
                    evaluation_config: { prompt: prompt.systemPrompt },
                    ...(modelConfig ? { model_configuration: modelConfig } : {}),
                })
                const label = getLinkedSourceLabel(linkedSource) ?? 'linked evaluation'
                const evalId = linkedSource.evaluationId
                lemonToast.success(`${label.charAt(0).toUpperCase()}${label.slice(1)} updated`, {
                    button: {
                        label: 'View',
                        action: () => router.actions.push(urls.llmAnalyticsEvaluation(evalId)),
                    },
                })
                for (const logic of llmEvaluationLogic.findAllMounted()) {
                    if (logic.props.evaluationId === evalId) {
                        logic.actions.loadEvaluation()
                    }
                }
            } catch (error: unknown) {
                lemonToast.error(getApiErrorDetail(error) || 'Failed to update evaluation')
            } finally {
                actions.saveComplete()
            }
        },

        saveAsNewPrompt: async ({ promptId, name }) => {
            posthog.capture('llma playground saved to source', { action: 'save_as_new_prompt' })
            const prompt = values.promptConfigs.find((p) => p.id === promptId)
            if (!prompt) {
                lemonToast.error('No prompt configuration to save')
                actions.saveComplete()
                return
            }
            try {
                await api.llmPrompts.create({ name, prompt: prompt.systemPrompt })
                // Link the playground to the newly created prompt
                actions.setPromptConfigs(
                    updatePromptConfigs(values.promptConfigs, prompt.id, (p) => ({
                        ...p,
                        sourceType: 'prompt',
                        sourcePromptName: name,
                        sourcePromptVersion: null,
                        sourceEvaluationId: null,
                        sourceEvaluationName: null,
                    }))
                )
                router.actions.replace(
                    combineUrl(urls.llmAnalyticsPlayground(), {
                        ...cleanSourceSearchParams(router.values.searchParams),
                        source_prompt_name: name,
                    }).url
                )
                lemonToast.success('Prompt saved', {
                    button: {
                        label: 'View',
                        action: () => router.actions.push(urls.llmAnalyticsPrompt(name)),
                    },
                })
            } catch (error: unknown) {
                lemonToast.error(getApiErrorDetail(error) || 'Failed to save prompt')
            } finally {
                actions.saveComplete()
            }
        },

        saveAsNewEvaluation: async ({ promptId, name, modelConfig }) => {
            posthog.capture('llma playground saved to source', { action: 'save_as_new_evaluation' })
            const prompt = values.promptConfigs.find((p) => p.id === promptId)
            if (!prompt) {
                lemonToast.error('No prompt configuration to save')
                actions.saveComplete()
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                lemonToast.error('Could not determine team')
                actions.saveComplete()
                return
            }
            try {
                // nosemgrep: prefer-codegen-api
                const created = await api.create<EvaluationConfig>(`/api/environments/${teamId}/evaluations/`, {
                    name,
                    evaluation_type: 'llm_judge',
                    evaluation_config: { prompt: prompt.systemPrompt },
                    model_configuration: modelConfig,
                    output_type: 'boolean',
                    conditions: [],
                    enabled: false,
                })
                // Link the playground to the newly created evaluation
                actions.setPromptConfigs(
                    updatePromptConfigs(values.promptConfigs, prompt.id, (p) => ({
                        ...p,
                        sourceType: 'evaluation',
                        sourcePromptName: null,
                        sourceEvaluationId: created.id,
                        sourceEvaluationName: created.name,
                    }))
                )
                router.actions.replace(
                    combineUrl(urls.llmAnalyticsPlayground(), {
                        ...cleanSourceSearchParams(router.values.searchParams),
                        source_evaluation_id: created.id,
                    }).url
                )
                lemonToast.success('Evaluation saved', {
                    button: {
                        label: 'View',
                        action: () => router.actions.push(urls.llmAnalyticsEvaluation(created.id)),
                    },
                })
            } catch (error: unknown) {
                lemonToast.error(getApiErrorDetail(error) || 'Failed to save evaluation')
            } finally {
                actions.saveComplete()
            }
        },
    })),

    urlToAction(({ actions, values, props }) => ({
        [urls.llmAnalyticsPlayground()]: (_, searchParams) => {
            // Consume a pending setup payload before the active-tab guard. The payload
            // is one-shot (set by openInPlayground) and at this point sceneLogic hasn't
            // updated activeTabId yet, so the guard below would incorrectly reject it.
            if (props.tabId) {
                const pending = consumePendingPlaygroundSetup()
                if (pending) {
                    actions.setupPlaygroundFromEvent(pending)
                    return
                }
            }

            // urlToAction fires on ALL mounted instances for the matching URL.
            // Only process URL params for the active tab to avoid cross-tab interference.
            if (props.tabId && sceneLogic.findMounted()?.values.activeTabId !== props.tabId) {
                return
            }

            const sourcePromptName =
                typeof searchParams?.source_prompt_name === 'string' ? searchParams.source_prompt_name : null
            const sourcePromptVersion = searchParams?.source_prompt_version
                ? Number(searchParams.source_prompt_version) || null
                : null
            const sourceEvaluationId =
                typeof searchParams?.source_evaluation_id === 'string' ? searchParams.source_evaluation_id : null

            if (sourcePromptName) {
                const currentSource = values.linkedSource
                if (
                    currentSource.type === 'prompt' &&
                    currentSource.promptName === sourcePromptName &&
                    currentSource.promptVersion === sourcePromptVersion
                ) {
                    return
                }
                actions.setupPlaygroundFromEvent({
                    sourceType: 'prompt',
                    sourcePromptName,
                    sourcePromptVersion: sourcePromptVersion ?? undefined,
                })
            } else if (sourceEvaluationId) {
                const currentSource = values.linkedSource
                if (currentSource.type === 'evaluation' && currentSource.evaluationId === sourceEvaluationId) {
                    return
                }
                actions.setupPlaygroundFromEvent({
                    sourceType: 'evaluation',
                    sourceEvaluationId,
                })
            } else {
                actions.clearLinkedSource()
            }
        },
    })),

    // afterMount runs synchronously during logic.mount(), before sceneLogic updates
    // activeTabId. This ensures the pending payload is consumed even when urlToAction
    // fires too early (before the active-tab check would pass).
    afterMount(({ actions, props }) => {
        if (!props.tabId) {
            return
        }
        const pending = consumePendingPlaygroundSetup()
        if (pending) {
            actions.setupPlaygroundFromEvent(pending)
        }
    }),
])
