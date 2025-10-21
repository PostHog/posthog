import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import type { EvaluationRun } from './evaluations/types'
import type { SpanAggregation } from './llmAnalyticsTraceDataLogic'
import {
    AnthropicInputMessage,
    AnthropicTextMessage,
    AnthropicThinkingMessage,
    AnthropicToolCallMessage,
    AnthropicToolResultMessage,
    CompatMessage,
    CompatToolCall,
    LiteLLMChoice,
    LiteLLMResponse,
    OpenAICompletionMessage,
    OpenAIToolCall,
    VercelSDKImageMessage,
    VercelSDKInputImageMessage,
    VercelSDKInputTextMessage,
    VercelSDKTextMessage,
} from './types'

function formatUsage(inputTokens: number, outputTokens?: number | null): string | null {
    return `${inputTokens} → ${outputTokens || 0} (∑ ${inputTokens + (outputTokens || 0)})`
}

export function formatLLMUsage(
    trace_or_event_or_aggregation: LLMTrace | LLMTraceEvent | SpanAggregation
): string | null {
    // Handle SpanAggregation
    if (
        'totalCost' in trace_or_event_or_aggregation &&
        'totalLatency' in trace_or_event_or_aggregation &&
        'hasGenerationChildren' in trace_or_event_or_aggregation
    ) {
        const aggregation = trace_or_event_or_aggregation as SpanAggregation
        return formatUsage(aggregation.inputTokens || 0, aggregation.outputTokens)
    }

    // Handle LLMTraceEvent
    if ('properties' in trace_or_event_or_aggregation) {
        const event = trace_or_event_or_aggregation as LLMTraceEvent
        if (typeof event.properties.$ai_input_tokens === 'number') {
            return formatUsage(event.properties.$ai_input_tokens, event.properties.$ai_output_tokens)
        }
    }

    // Handle LLMTrace
    const trace = trace_or_event_or_aggregation as LLMTrace
    if (typeof trace.inputTokens === 'number') {
        return formatUsage(trace.inputTokens, trace.outputTokens)
    }

    return null
}

export const LATENCY_MINUTES_DISPLAY_THRESHOLD_SECONDS = 90

export function formatLLMLatency(latency: number, showMinutes?: boolean): string {
    const roundedLatency = Math.round(latency * 100) / 100
    if (showMinutes && latency > LATENCY_MINUTES_DISPLAY_THRESHOLD_SECONDS) {
        const minutes = (latency / 60).toFixed(2)
        return `${roundedLatency} s (${minutes} m)`
    }
    return `${roundedLatency} s`
}

const usdFormatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
})

export function formatLLMCost(cost: number): string {
    return usdFormatter.format(cost)
}

export function isLLMEvent(item: LLMTrace | LLMTraceEvent): item is LLMTraceEvent {
    return 'properties' in item
}

function normalizeSessionId(value: unknown): string | null {
    return typeof value === 'string' && value.length > 0 ? value : null
}

function sessionIdFromEvents(events?: LLMTraceEvent[] | null): string | null {
    if (!events || events.length === 0) {
        return null
    }

    const uniqueSessionIds = events.reduce((acc, current) => {
        const candidate = normalizeSessionId(current.properties?.$session_id)
        if (candidate) {
            acc.add(candidate)
        }
        return acc
    }, new Set<string>())

    if (uniqueSessionIds.size !== 1) {
        return null
    }

    return Array.from(uniqueSessionIds)[0]
}

export function getSessionID(event: LLMTrace | LLMTraceEvent, childEvents?: LLMTraceEvent[]): string | null {
    if (isLLMEvent(event)) {
        if (event.event === '$ai_trace') {
            const directSessionId = normalizeSessionId(event.properties?.$session_id)

            return directSessionId ?? sessionIdFromEvents(childEvents)
        }

        return normalizeSessionId(event.properties?.$session_id)
    }

    return sessionIdFromEvents(childEvents ?? event.events)
}

export function getEventType(event: LLMTrace | LLMTraceEvent): string {
    if (isLLMEvent(event)) {
        switch (event.event) {
            case '$ai_generation':
                return 'generation'
            case '$ai_embedding':
                return 'embedding'
            case '$ai_trace':
                return 'trace'
            default:
                return 'span'
        }
    }
    return 'trace'
}

export function getRecordingStatus(event: LLMTrace | LLMTraceEvent): string | null {
    if (isLLMEvent(event)) {
        return event.properties.$recording_status || null
    }

    return event.events.find((e) => e.properties.$recording_status !== null)?.properties.$recording_status || null
}

export function isOpenAICompatToolCall(input: unknown): input is OpenAIToolCall {
    return (
        input !== null &&
        typeof input === 'object' &&
        'type' in input &&
        'function' in input &&
        input.type === 'function' &&
        typeof input.function === 'object' &&
        input.function !== null
    )
}

export function isOpenAICompatToolCallsArray(input: any): input is OpenAIToolCall[] {
    return Array.isArray(input) && input.every(isOpenAICompatToolCall)
}

export function isOpenAICompatMessage(output: unknown): output is OpenAICompletionMessage {
    return (
        !!output &&
        typeof output === 'object' &&
        'role' in output &&
        'content' in output &&
        (typeof output.content === 'string' || output.content === null)
    )
}

export function parseOpenAIToolCalls(toolCalls: OpenAIToolCall[]): CompatToolCall[] {
    const toolsWithParsedArguments = toolCalls.map((toolCall) => {
        let parsedArguments = toolCall.function.arguments

        if (typeof toolCall.function.arguments === 'string') {
            try {
                parsedArguments = JSON.parse(toolCall.function.arguments)
            } catch (e) {
                console.warn('Failed to parse tool call arguments as JSON:', toolCall.function.arguments, e)
                // Keep the original string if parsing fails
                parsedArguments = toolCall.function.arguments
            }
        }

        return {
            ...toolCall,
            function: {
                ...toolCall.function,
                arguments: parsedArguments,
            },
        }
    })

    return toolsWithParsedArguments
}

export function isAnthropicTextMessage(output: unknown): output is AnthropicTextMessage {
    return !!output && typeof output === 'object' && 'type' in output && output.type === 'text' && 'text' in output
}

export function isAnthropicToolCallMessage(output: unknown): output is AnthropicToolCallMessage {
    return !!output && typeof output === 'object' && 'type' in output && output.type === 'tool_use'
}

export function isAnthropicThinkingMessage(output: unknown): output is AnthropicThinkingMessage {
    return !!output && typeof output === 'object' && 'type' in output && output.type === 'thinking'
}

export function isAnthropicToolResultMessage(output: unknown): output is AnthropicToolResultMessage {
    return !!output && typeof output === 'object' && 'type' in output && output.type === 'tool_result'
}

export function isAnthropicRoleBasedMessage(input: unknown): input is AnthropicInputMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'role' in input &&
        'content' in input &&
        (typeof input.content === 'string' || Array.isArray(input.content))
    )
}

export function isVercelSDKTextMessage(input: unknown): input is VercelSDKTextMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'text' &&
        'content' in input &&
        typeof input.content === 'string'
    )
}

export function isVercelSDKImageMessage(input: unknown): input is VercelSDKImageMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'image' &&
        'content' in input &&
        typeof input.content === 'object' &&
        input.content !== null &&
        'image' in input.content &&
        typeof input.content.image === 'string'
    )
}

export function isVercelSDKInputImageMessage(input: unknown): input is VercelSDKInputImageMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'input_image' &&
        'image_url' in input &&
        typeof input.image_url === 'string'
    )
}

export function isVercelSDKInputTextMessage(input: unknown): input is VercelSDKInputTextMessage {
    return (
        !!input &&
        typeof input === 'object' &&
        'type' in input &&
        input.type === 'input_text' &&
        'text' in input &&
        typeof input.text === 'string'
    )
}

export function isLiteLLMChoice(input: unknown): input is LiteLLMChoice {
    return (
        !!input &&
        typeof input === 'object' &&
        'finish_reason' in input &&
        'index' in input &&
        'message' in input &&
        typeof input.message === 'object' &&
        input.message !== null
    )
}

export function isLiteLLMResponse(input: unknown): input is LiteLLMResponse {
    return (
        !!input &&
        typeof input === 'object' &&
        'choices' in input &&
        Array.isArray(input.choices) &&
        input.choices.every(isLiteLLMChoice)
    )
}

export const roleMap: Record<string, string> = {
    user: 'user',
    human: 'user',

    assistant: 'assistant',
    model: 'assistant',
    ai: 'assistant',
    bot: 'assistant',

    system: 'system',
    instructions: 'system',
}

export function normalizeRole(rawRole: unknown, fallback: string): string {
    if (typeof rawRole !== 'string') {
        return fallback
    }
    const lowercased = rawRole.toLowerCase()
    return roleMap[lowercased] || lowercased
}

/**
 * Normalizes a message from an LLM provider into a format that is compatible with the PostHog LLM Analytics schema.
 *
 * @param rawMessage - Original message from an LLM provider.
 * @param defaultRole - The default role to use if the message doesn't have one.
 * @returns The normalized message.
 */
export function normalizeMessage(rawMessage: unknown, defaultRole: string): CompatMessage[] {
    // Extract the role from the message if it exists, otherwise use defaultRole
    // This ensures we preserve roles when recursing into nested content
    const roleToUse =
        rawMessage && typeof rawMessage === 'object' && 'role' in rawMessage && typeof rawMessage.role === 'string'
            ? normalizeRole(rawMessage.role, defaultRole)
            : defaultRole

    // Handle new array-based content format (unified format with structured objects)
    // Only apply this if the array contains objects with 'type' field (not Anthropic-specific formats)
    // Supported types include: text, output_text, input_text, function, image, input_image
    if (
        rawMessage &&
        typeof rawMessage === 'object' &&
        'role' in rawMessage &&
        'content' in rawMessage &&
        typeof rawMessage.role === 'string' &&
        Array.isArray(rawMessage.content) &&
        rawMessage.content.length > 0 &&
        rawMessage.content.every(
            (item) =>
                item &&
                typeof item === 'object' &&
                'type' in item &&
                (item.type === 'text' ||
                    item.type === 'output_text' ||
                    item.type === 'input_text' ||
                    item.type === 'function' ||
                    item.type === 'image' ||
                    item.type === 'input_image')
        )
    ) {
        return [
            {
                role: roleToUse,
                content: rawMessage.content,
            },
        ]
    }

    if (isLiteLLMChoice(rawMessage)) {
        return normalizeMessage(rawMessage.message, roleToUse)
    }

    // Vercel SDK
    if (isVercelSDKTextMessage(rawMessage)) {
        return [
            {
                role: roleToUse,
                content: rawMessage.content,
            },
        ]
    }

    // Vercel SDK Input Image
    if (isVercelSDKInputImageMessage(rawMessage)) {
        return [
            {
                role: roleToUse,
                content: [
                    {
                        type: 'image',
                        image: rawMessage.image_url,
                    },
                ],
            },
        ]
    }

    // Vercel SDK Input Text
    if (isVercelSDKInputTextMessage(rawMessage)) {
        return [
            {
                role: roleToUse,
                content: rawMessage.text,
            },
        ]
    }

    // OpenAI
    if (isOpenAICompatMessage(rawMessage)) {
        return [
            {
                ...rawMessage,
                role: roleToUse,
                content: rawMessage.content,
                tool_calls: isOpenAICompatToolCallsArray(rawMessage.tool_calls)
                    ? parseOpenAIToolCalls(rawMessage.tool_calls)
                    : undefined,
                tool_call_id: rawMessage.tool_call_id,
            },
        ]
    }

    // Anthropic
    // Text object
    if (isAnthropicTextMessage(rawMessage)) {
        return [
            {
                role: roleToUse,
                content: rawMessage.text,
            },
        ]
    }
    // Tool call completion
    if (isAnthropicToolCallMessage(rawMessage)) {
        return [
            {
                role: roleToUse,
                content: '',
                tool_calls: [
                    {
                        type: 'function',
                        id: rawMessage.id,
                        function: {
                            name: rawMessage.name,
                            arguments: rawMessage.input,
                        },
                    },
                ],
            },
        ]
    }
    // Thinking
    if (isAnthropicThinkingMessage(rawMessage)) {
        return [
            {
                role: normalizeRole('assistant (thinking)', roleToUse),
                content: rawMessage.thinking,
            },
        ]
    }
    // Tool result completion
    if (isAnthropicToolResultMessage(rawMessage)) {
        if (Array.isArray(rawMessage.content)) {
            return rawMessage.content
                .map((content) => normalizeMessage(content, roleToUse))
                .flat()
                .map((msg) => ({
                    ...msg,
                    tool_call_id: rawMessage.tool_use_id,
                }))
        }
        return [
            {
                role: roleToUse,
                content: rawMessage.content,
                tool_call_id: rawMessage.tool_use_id,
            },
        ]
    }

    // Input message
    if (isAnthropicRoleBasedMessage(rawMessage)) {
        // Content is a nested array (tool responses, etc.)
        if (Array.isArray(rawMessage.content)) {
            return rawMessage.content.map((content) => normalizeMessage(content, roleToUse)).flat()
        }

        return [
            {
                role: roleToUse,
                content: rawMessage.content,
            },
        ]
    }
    // Unsupported message.
    console.warn("AI message isn't in a shape of any known AI provider", rawMessage)
    let cajoledContent: string // Let's do what we can
    if (typeof rawMessage === 'string') {
        cajoledContent = rawMessage
    } else if (
        typeof rawMessage === 'object' &&
        rawMessage !== null &&
        'content' in rawMessage &&
        typeof rawMessage.content === 'string'
    ) {
        cajoledContent = rawMessage.content
    } else {
        cajoledContent = JSON.stringify(rawMessage)
    }
    return [{ role: roleToUse, content: cajoledContent }]
}

export function normalizeMessages(messages: unknown, defaultRole: string, tools?: unknown): CompatMessage[] {
    const normalizedMessages: CompatMessage[] = []

    if (tools) {
        normalizedMessages.push({
            role: 'available tools',
            content: '',
            tools,
        })
    }

    if (Array.isArray(messages)) {
        normalizedMessages.push(...messages.map((message) => normalizeMessage(message, defaultRole)).flat())
    } else if (isLiteLLMResponse(messages)) {
        normalizedMessages.push(
            ...(messages.choices || []).map((choice) => normalizeMessage(choice, defaultRole)).flat()
        )
    } else if (typeof messages === 'object' && messages && 'choices' in messages && Array.isArray(messages.choices)) {
        normalizedMessages.push(...messages.choices.map((message) => normalizeMessage(message, defaultRole)).flat())
    } else if (typeof messages === 'string') {
        normalizedMessages.push({
            role: defaultRole,
            content: messages,
        })
    } else if (typeof messages === 'object' && messages !== null) {
        normalizedMessages.push(...normalizeMessage(messages, defaultRole))
    }

    return normalizedMessages
}

export function removeMilliseconds(timestamp: string): string {
    return dayjs(timestamp).utc().format('YYYY-MM-DDTHH:mm:ss[Z]')
}

export function getTraceTimestamp(timestamp: string): string {
    return dayjs(timestamp).utc().subtract(5, 'minutes').format('YYYY-MM-DDTHH:mm:ss[Z]')
}

export function formatLLMEventTitle(event: LLMTrace | LLMTraceEvent): string {
    if (isLLMEvent(event)) {
        if (event.event === '$ai_generation') {
            const spanName = event.properties.$ai_span_name
            if (spanName) {
                return `${spanName}`
            }
            const title = event.properties.$ai_model || 'Generation'
            if (event.properties.$ai_provider) {
                return `${title} (${event.properties.$ai_provider})`
            }

            return title
        }

        if (event.event === '$ai_embedding') {
            const spanName = event.properties.$ai_span_name
            if (spanName) {
                return `${spanName}`
            }
            const title = event.properties.$ai_model || 'Embedding'
            if (event.properties.$ai_provider) {
                return `${title} (${event.properties.$ai_provider})`
            }

            return title
        }

        return event.properties.$ai_span_name ?? 'Span'
    }

    return event.traceName ?? 'Trace'
}

/**
 * Lightweight XML-ish content detector for UI toggles.
 * - NOTE: Scans only the first 2KB for signals (to avoid performance issues with regex)
 */
export function looksLikeXml(input: unknown): boolean {
    if (typeof input !== 'string') {
        return false
    }

    const sampleLimit = 2048
    const sample = input.length > sampleLimit ? input.slice(0, sampleLimit) : input

    if (sample.indexOf('<') === -1 || sample.indexOf('>') === -1) {
        return false
    }

    if (sample.includes('</') || sample.includes('/>') || sample.includes('<?xml') || sample.includes('<!DOCTYPE')) {
        return true
    }

    const lt = sample.indexOf('<')
    const next = sample[lt + 1]
    const isNameStart =
        !!next && ((next >= 'A' && next <= 'Z') || (next >= 'a' && next <= 'z') || next === '_' || next === ':')
    return isNameStart
}

/**
 * Formats an ID for display by truncating it to the first and last 4 characters:
 * `1234567890` -> `1234...7890`
 * @param value - The string to format.
 * @returns The formatted string.
 */
export function truncateValue(value: unknown): string {
    if (value === null || value === undefined) {
        return '-'
    }

    const stringValue = String(value)

    if (stringValue.length <= 12) {
        return stringValue
    }

    return stringValue.slice(0, 4) + '...' + stringValue.slice(-4)
}

type RawEvaluationRunRow = [
    id: string,
    timestamp: string,
    evaluation_id: string,
    evaluation_name: string | null,
    generation_id: string,
    trace_id: string,
    result: boolean | string,
    reasoning: string | null,
]

export function mapEvaluationRunRow(row: RawEvaluationRunRow): EvaluationRun {
    return {
        id: row[0],
        timestamp: row[1],
        evaluation_id: row[2],
        evaluation_name: row[3] || 'Unknown Evaluation',
        generation_id: row[4],
        trace_id: row[5],
        result: row[6] === true || row[6] === 'true',
        reasoning: row[7] || 'No reasoning provided',
        status: 'completed' as const,
    }
}

export async function queryEvaluationRuns(params: {
    evaluationId?: string
    generationEventId?: string
    forceRefresh?: boolean
}): Promise<EvaluationRun[]> {
    const { evaluationId, generationEventId, forceRefresh } = params

    if (!evaluationId && !generationEventId) {
        throw new Error('Either evaluationId or generationEventId must be provided')
    }

    const propertyName = evaluationId ? '$ai_evaluation_id' : '$ai_target_event_id'
    const propertyValue = evaluationId || generationEventId

    const query = hogql`
        SELECT
            uuid,
            timestamp,
            properties.$ai_evaluation_id as evaluation_id,
            properties.$ai_evaluation_name as evaluation_name,
            properties.$ai_target_event_id as generation_id,
            properties.$ai_trace_id as trace_id,
            properties.$ai_evaluation_result as result,
            properties.$ai_evaluation_reasoning as reasoning
        FROM events
        WHERE
            event = '$ai_evaluation'
            AND ${hogql.raw(`properties.${propertyName}`)} = ${propertyValue}
        ORDER BY timestamp DESC
        LIMIT 100
    `

    const response = await api.queryHogQL(query, {
        ...(forceRefresh && { refresh: 'force_blocking' }),
    })

    return (response.results || []).map(mapEvaluationRunRow)
}
