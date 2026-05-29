import { ToolContext } from '@posthog/agent-shared'

export function makeCtx(overrides?: Partial<ToolContext>): ToolContext {
    const logs: Array<{ level: string; msg: string; meta?: Record<string, unknown> }> = []
    return {
        teamId: 1,
        applicationId: 'test-app',
        sessionId: 'test-session',
        integrations: {},
        secret: (_name: string) => undefined,
        log: (level, msg, meta) => {
            logs.push({ level, msg, meta })
        },
        ...overrides,
    }
}

/** Capture logs into a mutable array attached to the returned ctx. */
export function makeCapturingCtx(): {
    ctx: ToolContext
    logs: Array<{ level: string; msg: string; meta?: Record<string, unknown> }>
} {
    const logs: Array<{ level: string; msg: string; meta?: Record<string, unknown> }> = []
    const ctx: ToolContext = {
        teamId: 1,
        applicationId: 'test-app',
        sessionId: 'test-session',
        integrations: {},
        secret: () => undefined,
        log: (level, msg, meta) => {
            logs.push({ level, msg, meta })
        },
    }
    return { ctx, logs }
}
