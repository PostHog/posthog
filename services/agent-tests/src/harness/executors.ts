import type { Principal } from '@repo/ass-server/types'

/**
 * Test executors — pluggable `SessionExecutor` implementations the harness
 * swaps in via `ClusterOptions.executor`.
 */
import type { ExecutorTurnInput, ExecutorTurnOutput, SessionExecutor } from '@posthog/agent-runner'

/**
 * Completes every turn with a message that includes a stable, parseable
 * encoding of the principal the runner handed in. This is the test
 * substrate for "does the principal flow all the way through?" — the
 * harness reads SSE for the session and asserts the rendered principal.
 *
 * The message format is deliberately deterministic:
 *   `principal: <kind> caller=<caller> org=<orgId>`        // service
 *   `principal: user space=<spaceId> userId=<userId>`      // user
 *   `principal: none`                                       // null
 *
 * Tests use string matching rather than parsing — the goal is to prove
 * the value is reachable, not to round-trip serialise it.
 */
export class PrincipalEchoExecutor implements SessionExecutor {
    runTurn(input: ExecutorTurnInput): Promise<ExecutorTurnOutput> {
        const rendered = renderPrincipal(input.job.principal)
        return Promise.resolve({
            kind: 'completed',
            message: {
                role: 'assistant',
                content: rendered,
                at: new Date().toISOString(),
            },
            // Include the rendered string in `output` too — the worker
            // publishes `output` on the `session_completed` SSE event but
            // does NOT publish the assistant `message` as a separate event,
            // so this is the only way for the harness's SSE collector to
            // observe what the executor saw.
            output: { renderedPrincipal: rendered, principal: input.job.principal },
        })
    }
}

export function renderPrincipal(principal: Principal | null): string {
    if (principal === null) {
        return 'principal: none'
    }
    if (principal.kind === 'service') {
        return `principal: service caller=${principal.caller} org=${principal.orgId}`
    }
    return `principal: user space=${principal.spaceId} userId=${principal.userId} provider=${principal.provider}`
}
