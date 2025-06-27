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
        typeof output.content === 'string'
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
/**
 * Normalizes a message from an LLM provider into a format that is compatible with the PostHog LLM Observability schema.
 *
 * @param output - Original message from an LLM provider.
 * @param defaultRole - Optional default role to use if the message doesn't have one.
 * @returns The normalized message.
 */
export function normalizeMessage(output: unknown, defaultRole?: string): CompatMessage[] {
    const role = defaultRole || 'assistant'

    // Vercel SDK
    if (isVercelSDKTextMessage(output)) {
        return [
            {
                role,
                content: output.content,
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
            role: 'user',
            content: typeof output === 'string' ? output : JSON.stringify(output),
        },
    ]
}

export function normalizeMessages(messages: unknown, defaultRole?: string, tools?: unknown): CompatMessage[] {
    const normalizedMessages: CompatMessage[] = []

    if (tools) {
        normalizedMessages.push({
            role: 'tools',
            content: '',
            tools,
        })
    }

    if (Array.isArray(messages)) {
        normalizedMessages.push(...messages.map((message) => normalizeMessage(message, defaultRole)).flat())
    }

    if (typeof messages === 'object' && messages && 'choices' in messages && Array.isArray(messages.choices)) {
        normalizedMessages.push(...messages.choices.map((message) => normalizeMessage(message, defaultRole)).flat())
    }

    if (typeof messages === 'string') {
        normalizedMessages.push({
            role: 'user',
            content: messages,
        })
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

        return event.properties.$ai_span_name ?? 'Span'
    }

    return event.traceName ?? 'Trace'
}
