import type { ToolInvocation } from '../types/streamTypes'
import type { ToolCallMessage } from '../types/toolTypes'
import { resolveToolCall } from './toolResolver'

/** Maps a raw merged `ToolInvocation` into the flat `ToolCallMessage` the registry renderers read. */
export function toolInvocationToMessage(invocation: ToolInvocation | undefined): ToolCallMessage | null {
    if (!invocation) {
        return null
    }
    const resolved = resolveToolCall(invocation)
    return {
        id: invocation.toolCallId,
        resolvedKey: resolved.resolvedKey,
        rawServerName: invocation.rawServerName,
        rawToolName: invocation.rawToolName,
        innerToolName: resolved.innerToolName,
        claudeToolName: resolved.claudeToolName,
        rawInput: invocation.input,
        innerInput: resolved.innerInput,
        rawOutput: invocation.output,
        content: invocation.contentBlocks,
        status: invocation.status,
        title: invocation.title,
        kind: invocation.kind,
        locations: invocation.locations,
        error: invocation.error,
    }
}
