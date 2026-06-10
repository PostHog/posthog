/**
 * The supervisor relay (tier 1) for in-sandbox coding agents — see
 * docs/agent-platform/plans/agent-sandbox-tiers.md §4.
 *
 * It does NOT run an LLM. It provisions a tier-2 coding sandbox, mints the
 * RS256 connection token, opens the harness's SSE `/events` stream (which
 * initializes the session), relays the user's turn over JSON-RPC, parses the
 * ACP event stream, brokers option-based permission requests through an
 * approval callback (→ the approval machinery in prod), and resolves the
 * outcome. The LLM lives in the sandbox; this is the control plane around it.
 */

import {
    CodingEvent,
    CodingLaunchConfig,
    CodingSandbox,
    CodingSandboxPool,
    PermissionOption,
    generateHarnessKeypair,
    mintHarnessJwt,
    parseFrame,
} from '@posthog/agent-shared'

export interface ApprovalRequest {
    requestId: string
    options: PermissionOption[]
    tool?: string
    summary?: string
}

export interface ApprovalDecision {
    optionId: string
    customInput?: string
}

export interface CodingSessionDeps {
    pool: CodingSandboxPool
    /** Broker a gated action — pick an optionId. In prod this drives the approval queue. */
    approve: (req: ApprovalRequest) => Promise<ApprovalDecision>
    /** Fan-out hook for bus + log_entries. Called for every normalized event. */
    onEvent?: (event: CodingEvent) => void
}

export interface RunCodingSessionInput {
    sessionId: string
    teamId: number
    launch: CodingLaunchConfig
    userMessage: string
    principal?: { userId?: number; distinctId?: string }
    workspaceMount?: { hostPath: string; readonly: boolean }
    timeoutMs?: number
}

export interface CodingSessionResult {
    state: 'completed' | 'failed'
    result?: unknown
    assistantText: string[]
    toolCalls: { tool?: string; command?: string }[]
    usage: { inputTokens: number; outputTokens: number; costUsd: number }
    events: CodingEvent[]
    approvals: ApprovalRequest[]
}

const DEFAULT_TIMEOUT_MS = 30 * 60 * 1000

export async function runCodingSession(
    input: RunCodingSessionInput,
    deps: CodingSessionDeps
): Promise<CodingSessionResult> {
    const events: CodingEvent[] = []
    const assistantText: string[] = []
    const toolCalls: { tool?: string; command?: string }[] = []
    const approvals: ApprovalRequest[] = []
    const usage = { inputTokens: 0, outputTokens: 0, costUsd: 0 }

    let sandbox: CodingSandbox | undefined
    let userMessageSent = false
    let settle: (r: CodingSessionResult) => void
    const done = new Promise<CodingSessionResult>((resolve) => (settle = resolve))
    let settled = false
    const finish = (state: 'completed' | 'failed', result?: unknown): void => {
        if (settled) {
            return
        }
        settled = true
        settle({ state, result, assistantText, toolCalls, usage, events, approvals })
    }

    const handle = (event: CodingEvent): void => {
        events.push(event)
        deps.onEvent?.(event)
        switch (event.kind) {
            case 'assistant_text':
                if (event.text) {
                    assistantText.push(event.text)
                }
                return
            case 'tool_call':
                toolCalls.push({ tool: event.tool, command: event.command })
                return
            case 'usage':
                usage.inputTokens += event.inputTokens
                usage.outputTokens += event.outputTokens
                usage.costUsd += event.costUsd ?? 0
                return
            case 'permission_request': {
                const req: ApprovalRequest = {
                    requestId: event.requestId,
                    options: event.options,
                    tool: event.tool,
                    summary: event.summary,
                }
                approvals.push(req)
                void deps
                    .approve(req)
                    .then((decision) =>
                        sandbox?.command({
                            method: 'permission_response',
                            params: {
                                requestId: event.requestId,
                                optionId: decision.optionId,
                                customInput: decision.customInput,
                            },
                        })
                    )
                    .catch(() => undefined)
                return
            }
            // Boot-time auto-init in background mode emits its own turn_complete
            // before our message; only treat completion as ours once sent.
            case 'turn_complete':
                if (userMessageSent) {
                    finish('completed', assistantText.join(''))
                }
                return
            case 'task_complete':
                if (userMessageSent) {
                    finish('completed', event.result)
                }
                return
            case 'error':
                if (userMessageSent) {
                    finish('failed', event.message)
                }
                return
            default:
                return
        }
    }

    const taskId = `task-${input.sessionId}`
    const runId = `run-${input.sessionId}`
    const keypair = generateHarnessKeypair()
    const token = mintHarnessJwt(keypair.privateKeyPem, {
        run_id: runId,
        task_id: taskId,
        team_id: input.teamId,
        user_id: input.principal?.userId ?? 0,
        distinct_id: input.principal?.distinctId ?? `coding-${input.sessionId}`,
        mode: 'background',
    })

    const timeoutMs = input.timeoutMs ?? DEFAULT_TIMEOUT_MS
    const timer = setTimeout(() => {
        void sandbox?.command({ method: 'cancel' })
        finish('failed', 'timeout')
    }, timeoutMs)

    let subscription: { close: () => void } | undefined
    try {
        sandbox = await deps.pool.acquireForSession({
            sessionId: input.sessionId,
            teamId: input.teamId,
            launch: input.launch,
            auth: { publicKeyPem: keypair.publicKeyPem, token },
            harnessIds: { taskId, runId },
            workspaceMount: input.workspaceMount,
            sessionTimeoutMs: timeoutMs,
        })

        // Opening /events initializes the session. Give it a beat to attach
        // before sending the turn.
        subscription = sandbox.openEvents((frame) => {
            const event = parseFrame(frame)
            if (event) {
                handle(event)
            }
        })
        await new Promise((r) => setTimeout(r, 1_000))

        // `/command` user_message is synchronous — it blocks until the turn
        // completes (the turn outcome comes back in the response). The
        // `turn_complete` SSE frame arrives DURING this await, so mark the turn
        // as ours before sending, not after.
        userMessageSent = true
        const ack = await sandbox.command({ method: 'user_message', params: { content: input.userMessage } })
        if (ack.error) {
            finish('failed', `harness rejected user_message: ${ack.error.message}`)
        }

        return await done
    } finally {
        clearTimeout(timer)
        subscription?.close()
        await deps.pool.release(input.sessionId).catch(() => undefined)
    }
}
