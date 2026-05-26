import type { Principal } from '@repo/ass-server/types'

import { SessionMessage, SessionState } from './state'
import { ToolCall } from './tools/types'

/**
 * The contract the worker drives a single turn through. Concrete implementations wrap
 * the Claude Agent SDK (real) or a deterministic script (tests). Keeping this as an
 * interface means the worker doesn't import the SDK directly — and the runtime can
 * swap executors per revision in the future (Anthropic / Bedrock / local).
 */
export interface SessionExecutor {
    /**
     * Run a single turn against the current state. The returned outcome tells the worker
     * whether to ack the job, reschedule it (after a tool call or an explicit suspension),
     * or fail it.
     */
    runTurn(input: ExecutorTurnInput): Promise<ExecutorTurnOutput>
}

export interface ExecutorJobContext {
    readonly sessionId: string
    readonly teamId: number
    /** Null only on legacy/orphan jobs without a bound application — real executors should fail those. */
    readonly applicationId: string | null
    readonly revisionId: string | null
    /** Decrypted application env. Used by the executor to load bundles, resolve secrets, etc. */
    readonly secrets: Record<string, string>
    /**
     * Caller principal stamped at ingress, loaded by the worker from
     * `agent_sessions.principal`. `null` for public agents (no identity to
     * attribute the run to). Executors that want to inject who-is-calling
     * into the model context — system prompt prefix, meta-tool result, etc.
     * — read it here. See agent-stack/docs/auth-and-identity.md.
     */
    readonly principal: Principal | null
}

export interface ExecutorTurnInput {
    readonly state: SessionState
    /** Latest /send/:id messages flushed into state.pendingInputs. */
    readonly newInputs: readonly { content: string; at: string }[]
    /** Job identity + decrypted secrets — the executor needs these to fetch the bundle and run the SDK. */
    readonly job: ExecutorJobContext
}

export type ExecutorTurnOutput =
    | {
          /** The SDK requested a tool call. The worker executes it, appends the result, and reschedules for another turn. */
          kind: 'tool_call'
          message: SessionMessage
          call: ToolCall & { id: string }
      }
    | {
          /** Run finished cleanly; the worker acks the job and publishes the output. */
          kind: 'completed'
          message: SessionMessage
          output: unknown
      }
    | {
          /** SDK voluntarily yielded to await /send/:id input. The worker reschedules and parks the lock. */
          kind: 'awaiting_input'
          message: SessionMessage
          reason: string | null
      }
    | {
          /** Hard failure inside the turn. The worker fails the job. */
          kind: 'failed'
          error: string
      }
    | {
          /** The run was aborted by a client `/cancel/:id`. The worker marks the job canceled. */
          kind: 'cancelled'
      }
