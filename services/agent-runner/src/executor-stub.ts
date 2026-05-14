import { ExecutorTurnOutput, SessionExecutor } from './executor'

/**
 * Dev-mode executor: completes every turn immediately with an echo of the initial input.
 *
 * Lives here (not in tests) so the runner can boot end-to-end before the real Claude
 * Agent SDK executor lands. Useful for local stack smoke tests — seed a session, watch
 * it move from available → running → completed without needing Anthropic credentials.
 */
export class EchoExecutor implements SessionExecutor {
    runTurn(input: { state: { initialInput: unknown } }): Promise<ExecutorTurnOutput> {
        return Promise.resolve({
            kind: 'completed',
            message: {
                role: 'assistant',
                content: 'echo executor — replace with the Claude Agent SDK executor',
                at: new Date().toISOString(),
            },
            output: { echo: input.state.initialInput ?? null },
        })
    }
}

/** @deprecated Renamed to `EchoExecutor`. Kept as an alias during the SDK-executor rollout. */
export const NotImplementedExecutor = EchoExecutor
