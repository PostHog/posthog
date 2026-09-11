import type { ToolCallMessage } from '../../types/toolTypes'

export function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

export function getToolOutputRecord(message: ToolCallMessage): Record<string, unknown> | null {
    const output = asRecord(message.rawOutput)
    if (!output || output.isError === true || message.status === 'failed') {
        return null
    }

    // The model's optimized text can omit fields or use a lossy format. Widgets consume
    // the handler object carried by MCP metadata through ACP rawOutput instead.
    const meta = asRecord(output._meta)
    const data = asRecord(meta?.['com.posthog.mcp/app_data']) ?? asRecord(output.structuredContent)
    if (data) {
        return data
    }

    // Notebook entities also carry content, so distinguish their payload from a text-only MCP envelope.
    return Object.keys(output).every((key) =>
        ['content', 'structuredContent', 'isError', '_meta', '__execBuiltPayload'].includes(key)
    )
        ? null
        : output
}
