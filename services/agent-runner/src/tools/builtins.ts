import { getBuiltin, isBuiltinId } from '@posthog/agent-core'

import { ToolCall, ToolContext, ToolHandler, ToolResult } from './types'

/**
 * Concrete native implementations for the built-in ids declared in agent-core's registry.
 * Kept separate from the registry itself so the runner owns "how it runs" while the
 * registry owns "what's allowed". Both the runner and the future validator can ask the
 * registry whether an id is known; only the runner knows how to execute it.
 */
type BuiltinExecutor = (parsedArgs: unknown, ctx: ToolContext) => Promise<unknown>

const EXECUTORS: Record<string, BuiltinExecutor> = {
    'posthog.events.capture': (args, ctx) => {
        // v1 stub: log the captured event. The real implementation will go through
        // posthog-node once we wire credentials through the secrets path.
        return Promise.resolve({
            captured: true,
            teamId: ctx.teamId,
            event: args,
        })
    },
    'posthog.feature_flags.evaluate': () => {
        return Promise.resolve({ enabled: false, variant: null })
    },
    'http.fetch': async (args) => {
        const { url, method, headers, body, timeoutMs } = args as {
            url: string
            method: string
            headers?: Record<string, string>
            body?: string
            timeoutMs: number
        }
        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), timeoutMs)
        try {
            const response = await fetch(url, {
                method,
                headers,
                body,
                signal: controller.signal,
            })
            const text = await response.text()
            return {
                status: response.status,
                headers: Object.fromEntries(response.headers.entries()),
                body: text,
            }
        } finally {
            clearTimeout(timer)
        }
    },
}

class BuiltinHandler implements ToolHandler {
    constructor(public readonly id: string) {}

    async invoke(call: ToolCall, ctx: ToolContext): Promise<ToolResult> {
        const spec = getBuiltin(this.id)
        if (!spec) {
            return { ok: false, error: `builtin ${this.id} is not declared in the registry` }
        }
        const parsed = spec.args.safeParse(call.args)
        if (!parsed.success) {
            return { ok: false, error: `builtin ${this.id} args invalid: ${parsed.error.message}` }
        }
        const executor = EXECUTORS[this.id]
        if (!executor) {
            return { ok: false, error: `builtin ${this.id} is declared but not implemented in the runner` }
        }
        try {
            const value = await executor(parsed.data, ctx)
            return { ok: true, value }
        } catch (err) {
            return { ok: false, error: String(err) }
        }
    }
}

export function makeBuiltinHandler(id: string): ToolHandler | null {
    if (!isBuiltinId(id)) {
        return null
    }
    return new BuiltinHandler(id)
}
