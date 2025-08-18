import { dayjs } from 'lib/dayjs'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import type { SpanAggregation } from './llmObservabilityTraceDataLogic'
import {
    AnthropicInputMessage,
    AnthropicTextMessage,
    AnthropicThinkingMessage,
    AnthropicToolCallMessage,
    AnthropicToolResultMessage,
    CompatMessage,
    CompatToolCall,
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

export function formatLLMLatency(latency: number): string {
    return `${Math.round(latency * 100) / 100} s`
}

const usdFormatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
})

export function formatLLMCost(cost: number): string {
    return usdFormatter.format(cost)
}

export function isLLMTraceEvent(item: LLMTrace | LLMTraceEvent): item is LLMTraceEvent {
    return 'properties' in item
}

export function hasSessionID(event: LLMTrace | LLMTraceEvent): boolean {
    if (isLLMTraceEvent(event)) {
        return 'properties' in event && typeof event.properties.$session_id === 'string'
    }
    return '$session_id' in event
}

export function getSessionID(event: LLMTrace | LLMTraceEvent): string | null {
    if (isLLMTraceEvent(event)) {
        return event.properties.$session_id || null
    }

    return event.events.find((e) => e.properties.$session_id !== null)?.properties.$session_id || null
}

export function getRecordingStatus(event: LLMTrace | LLMTraceEvent): string | null {
    if (isLLMTraceEvent(event)) {
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
    const toolsWithParsedArguments = toolCalls.map((toolCall) => ({
        ...toolCall,
        function: {
            ...toolCall.function,
            arguments:
                typeof toolCall.function.arguments === 'string'
                    ? JSON.parse(toolCall.function.arguments)
                    : toolCall.function.arguments,
        },
    }))

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
/**
 * Normalizes a message from an LLM provider into a format that is compatible with the PostHog LLM Observability schema.
 *
 * @param output - Original message from an LLM provider.
 * @param defaultRole - Optional default role to use if the message doesn't have one.
 * @returns The normalized message.
 */
export function normalizeMessage(output: unknown, defaultRole?: string): CompatMessage[] {
    const role = defaultRole || 'user'

    // Handle new array-based content format (unified format with structured objects)
    // Only apply this if the array contains objects with 'type' field (not Anthropic-specific formats)
    if (
        output &&
        typeof output === 'object' &&
        'role' in output &&
        'content' in output &&
        typeof output.role === 'string' &&
        Array.isArray(output.content) &&
        output.content.length > 0 &&
        output.content.every(
            (item) =>
                item &&
                typeof item === 'object' &&
                'type' in item &&
                (item.type === 'text' || item.type === 'function' || item.type === 'image')
        )
    ) {
        return [
            {
                role: output.role === 'user' ? 'user' : 'assistant',
                content: output.content,
            },
        ]
    }

    // Vercel SDK
    if (isVercelSDKTextMessage(output)) {
        return [
            {
                role,
                content: output.content,
            },
        ]
    }

    // Vercel SDK Input Image
    if (isVercelSDKInputImageMessage(output)) {
        return [
            {
                role,
                content: [
                    {
                        type: 'image',
                        image: output.image_url,
                    },
                ],
            },
        ]
    }

    // Vercel SDK Input Text
    if (isVercelSDKInputTextMessage(output)) {
        return [
            {
                role,
                content: output.text,
            },
        ]
    }

    // OpenAI
    if (isOpenAICompatMessage(output)) {
        return [
            {
                ...output,
                role: output.role,
                content: output.content,
                tool_calls: isOpenAICompatToolCallsArray(output.tool_calls)
                    ? parseOpenAIToolCalls(output.tool_calls)
                    : undefined,
                tool_call_id: output.tool_call_id,
            },
        ]
    }

    // Anthropic
    // Text object
    if (isAnthropicTextMessage(output)) {
        return [
            {
                role,
                content: output.text,
            },
        ]
    }
    // Tool call completion
    if (isAnthropicToolCallMessage(output)) {
        return [
            {
                role,
                content: '',
                tool_calls: [
                    {
                        type: 'function',
                        id: output.id,
                        function: {
                            name: output.name,
                            arguments: output.input,
                        },
                    },
                ],
            },
        ]
    }
    // Thinking
    if (isAnthropicThinkingMessage(output)) {
        return [
            {
                role: 'assistant (thinking)',
                content: output.thinking,
            },
        ]
    }
    // Tool result completion
    if (isAnthropicToolResultMessage(output)) {
        if (Array.isArray(output.content)) {
            return output.content
                .map((content) => normalizeMessage(content, role))
                .flat()
                .map((message) => ({
                    ...message,
                    tool_call_id: output.tool_use_id,
                }))
        }
        return [
            {
                role,
                content: output.content,
                tool_call_id: output.tool_use_id,
            },
        ]
    }

    // Input message
    if (isAnthropicRoleBasedMessage(output)) {
        // Content is a nested array (tool responses, etc.)
        if (Array.isArray(output.content)) {
            return output.content.map((content) => normalizeMessage(content, output.role)).flat()
        }

        return [
            {
                role: output.role,
                content: output.content,
            },
        ]
    }
    // Unsupported message.
    console.warn('Unsupported AI message type', output)
    return [
        {
            role: role,
            content: typeof output === 'string' ? output : JSON.stringify(output),
        },
    ]
}

export function normalizeMessages(messages: unknown, defaultRole?: string, tools?: unknown): CompatMessage[] {
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
    } else if (typeof messages === 'object' && messages && 'choices' in messages && Array.isArray(messages.choices)) {
        normalizedMessages.push(...messages.choices.map((message) => normalizeMessage(message, defaultRole)).flat())
    } else if (typeof messages === 'string') {
        normalizedMessages.push({
            role: defaultRole || 'user',
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

export function formatLLMEventTitle(event: LLMTrace | LLMTraceEvent): string {
    if (isLLMTraceEvent(event)) {
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
