import { makeBuiltinHandler } from './builtins'
import { META_TOOL_HANDLERS, META_TOOL_IDS } from './meta'
import { ToolCall, ToolContext, ToolHandler, ToolResult } from './types'

const META_HANDLER_INDEX = new Map<string, ToolHandler>(META_TOOL_HANDLERS.map((h) => [h.id, h]))

/**
 * Resolves a tool id to a handler and runs it. v1 is native-only: meta tools and built-ins
 * are looked up in-process. Unknown ids return a structured failure rather than throwing.
 */
export async function executeTool(call: ToolCall & { id: string }, ctx: ToolContext): Promise<ToolResult> {
    const handler = resolveHandler(call.id)
    if (!handler) {
        return { ok: false, error: `unknown tool id: ${call.id}` }
    }
    return handler.invoke(call, ctx)
}

export function resolveHandler(id: string): ToolHandler | null {
    if (META_TOOL_IDS.has(id)) {
        return META_HANDLER_INDEX.get(id) ?? null
    }
    return makeBuiltinHandler(id)
}
