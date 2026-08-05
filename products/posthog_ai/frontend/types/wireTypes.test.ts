import {
    type AcpNotification,
    type PosthogNotificationParamsByMethod,
    type StoredLogEntry,
    isKeepaliveFrame,
    isKnownSessionUpdate,
    isNotificationFrame,
    isPermissionRequestFrame,
    isPosthogNotification,
    isSessionUpdateNotification,
    isSessionUpdateUsage,
    isTaskRunStateFrame,
    hasUsageBreakdown,
    hasUsageUsed,
} from './wireTypes'

const TIMESTAMP = '2026-06-11T09:00:00.000000+00:00'
const RUN_ID = '3d2f3e7a-5c1b-4f7e-9d51-0a9b8c7d6e5f'
const TASK_ID = '9b8a7c6d-5e4f-3a2b-1c0d-e9f8a7b6c5d4'

function notification(method: string, params?: Record<string, unknown>): StoredLogEntry {
    return {
        type: 'notification',
        timestamp: TIMESTAMP,
        notification: { jsonrpc: '2.0', method, ...(params !== undefined ? { params } : {}) },
    }
}

function sessionUpdate(update: Record<string, unknown>): StoredLogEntry {
    return notification('session/update', { sessionId: 'sess_a1b2c3', update })
}

// Canonical `_posthog/*` payloads as the emitters produce them (products/tasks for the core
// methods, the agent adapters for the rest).
const NOTIFICATION_PARAMS_BY_METHOD: { [M in keyof PosthogNotificationParamsByMethod]: Record<string, unknown>[] } = {
    '_posthog/console': [{ sessionId: RUN_ID, level: 'info', message: 'Provisioning sandbox' }],
    '_posthog/progress': [
        {
            sessionId: RUN_ID,
            step: 'clone_repository',
            status: 'in_progress',
            label: 'Cloning repository',
            group: 'setup',
            detail: 'PostHog/posthog @ master',
        },
        { sessionId: RUN_ID, step: 'start_agent', status: 'completed', label: 'Starting agent', group: 'setup' },
    ],
    '_posthog/sandbox_output': [{ sessionId: RUN_ID, stdout: 'ok\n', stderr: '', exitCode: 0 }],
    '_posthog/user_message': [{ content: 'Why did checkout conversion drop last week?' }],
    '_posthog/usage_update': [
        {
            sessionId: 'sess_a1b2c3',
            used: { inputTokens: 12450, outputTokens: 980, cachedReadTokens: 110200, cachedWriteTokens: 2048 },
            cost: { amount: 0.42, currency: 'USD' },
        },
        {
            sessionId: 'sess_a1b2c3',
            used: { inputTokens: 900, outputTokens: 120, cachedReadTokens: 0, cachedWriteTokens: 0 },
            cost: null,
        },
        {
            sessionId: 'sess_a1b2c3',
            breakdown: {
                systemPrompt: 3100,
                tools: 8200,
                rules: 450,
                skills: 0,
                mcp: 12700,
                subagents: 0,
                conversation: 20410,
            },
        },
        {
            // Claude combined frame: used + cost (a bare number) + breakdown together.
            sessionId: 'sess_a1b2c3',
            used: { inputTokens: 5000, outputTokens: 600, cachedReadTokens: 100, cachedWriteTokens: 0 },
            cost: 0.18,
            breakdown: { systemPrompt: 2000, tools: 4000, conversation: 9000 },
        },
    ],
    '_posthog/status': [
        { sessionId: 'sess_a1b2c3', status: 'compacting' },
        { sessionId: 'sess_a1b2c3', status: 'compacting', isComplete: true },
    ],
    '_posthog/compact_boundary': [{ sessionId: 'sess_a1b2c3', trigger: 'auto', preTokens: 168000, contextSize: 54000 }],
    '_posthog/task_notification': [
        {
            sessionId: 'sess_a1b2c3',
            taskId: TASK_ID,
            status: 'completed',
            summary: 'Analysis written to report.md',
            outputFile: 'report.md',
        },
    ],
    '_posthog/error': [
        { message: 'Model request failed after 3 retries', classification: 'provider_error' },
        { message: 'Tool execution timed out' },
    ],
    '_posthog/sdk_session': [{ taskRunId: RUN_ID, sessionId: 'sess_a1b2c3', adapter: 'claude' }],
    '_posthog/resources_used': [
        {
            sessionId: 'sess_a1b2c3',
            products: [
                { id: 'product_analytics', label: 'Product analytics' },
                { id: 'session_replay', label: 'Session replay' },
            ],
        },
    ],
    '_posthog/permission_request': [
        {
            requestId: 'perm-1',
            toolCallId: 'toolu_01',
            options: [
                { optionId: 'allow_once', name: 'Allow once', kind: 'allow_once' },
                { optionId: 'reject', name: 'Reject', kind: 'reject' },
            ],
            toolCall: {
                toolCallId: 'toolu_01',
                title: 'Run SQL query',
                kind: 'execute',
                rawInput: { command: 'call execute-sql {"query": "SELECT 1"}' },
            },
        },
    ],
    '_posthog/permission_resolved': [{ requestId: 'perm-1', toolCallId: 'toolu_01', optionId: 'allow_once' }],
    '_posthog/run_started': [{ sessionId: 'sess_a1b2c3', runId: RUN_ID, taskId: TASK_ID, agentVersion: '1.42.0' }],
    '_posthog/turn_complete': [{ sessionId: 'sess_a1b2c3', stopReason: 'end_turn' }],
}

const KNOWN_POSTHOG_METHODS = Object.keys(NOTIFICATION_PARAMS_BY_METHOD) as (keyof PosthogNotificationParamsByMethod)[]

const SESSION_UPDATE_CASES: { kind: string; update: Record<string, unknown> }[] = [
    {
        kind: 'agent_message_chunk',
        update: {
            sessionUpdate: 'agent_message_chunk',
            messageId: 'msg_01',
            content: { type: 'text', text: 'Looking at the funnel' },
        },
    },
    { kind: 'agent_message_chunk', update: { sessionUpdate: 'agent_message_chunk', text: ' now.' } },
    {
        kind: 'agent_thought_chunk',
        update: {
            sessionUpdate: 'agent_thought_chunk',
            content: { type: 'text', text: 'Let me reason about the funnel drop-off' },
        },
    },
    {
        kind: 'agent_message',
        update: {
            sessionUpdate: 'agent_message',
            messageId: 'msg_01',
            content: { type: 'text', text: 'Looking at the funnel now.' },
        },
    },
    {
        kind: 'tool_call',
        update: {
            sessionUpdate: 'tool_call',
            toolCallId: 'toolu_02',
            serverName: 'posthog',
            toolName: 'exec',
            title: 'exec',
            kind: 'execute',
            status: 'pending',
            rawInput: { command: 'call insight-create {"name": "Weekly signups"}' },
        },
    },
    {
        kind: 'tool_call_update',
        update: {
            sessionUpdate: 'tool_call_update',
            toolCallId: 'toolu_02',
            status: 'completed',
            rawOutput: { short_id: 'abc123', name: 'Weekly signups' },
            content: [{ type: 'content', content: { type: 'text', text: '{"short_id": "abc123"}' } }],
        },
    },
    {
        kind: 'tool_call_update',
        update: {
            sessionUpdate: 'tool_call_update',
            toolCallId: 'toolu_04',
            status: 'failed',
            error: { message: 'Permission denied by user' },
            _meta: {
                claudeCode: {
                    toolName: 'execute-sql',
                    toolResponse: {
                        decisionReason: 'User rejected the permission request',
                        decisionReasonType: 'user_rejection',
                        message: 'Permission denied',
                    },
                },
            },
        },
    },
    { kind: 'current_mode_update', update: { sessionUpdate: 'current_mode_update', currentModeId: 'default' } },
]

function notificationOf(frame: unknown): AcpNotification {
    if (!isNotificationFrame(frame)) {
        throw new Error('expected a notification frame')
    }
    return frame.notification
}

describe('wireTypes guards', () => {
    it.each([
        ['queued', { type: 'task_run_state', run_id: RUN_ID, task_id: TASK_ID, status: 'queued', stage: null }],
        [
            'failed',
            {
                type: 'task_run_state',
                run_id: RUN_ID,
                task_id: TASK_ID,
                status: 'failed',
                error_message: 'Agent server crashed: sandbox out of memory',
                completed_at: TIMESTAMP,
            },
        ],
    ])('classifies a %s task_run_state frame and exposes snake_case fields', (_name, frame) => {
        expect(isTaskRunStateFrame(frame)).toBe(true)
        expect(isNotificationFrame(frame)).toBe(false)
        expect(isKeepaliveFrame(frame)).toBe(false)
        expect(isPermissionRequestFrame(frame)).toBe(false)
        if (isTaskRunStateFrame(frame) && frame.status === 'failed') {
            expect(frame.error_message).toEqual(expect.any(String))
        }
    })

    it('classifies keepalive and top-level permission_request frames', () => {
        const keepalive = { type: 'keepalive' }
        expect(isKeepaliveFrame(keepalive)).toBe(true)
        expect(isNotificationFrame(keepalive)).toBe(false)

        const permission = {
            type: 'permission_request',
            requestId: 'perm-2',
            toolCallId: 'toolu_05',
            options: [{ optionId: 'allow_once', name: 'Allow once', kind: 'allow_once' }],
            toolCall: { toolCallId: 'toolu_05', title: 'Delete dashboard', kind: 'execute' },
        }
        expect(isPermissionRequestFrame(permission)).toBe(true)
        expect(isNotificationFrame(permission)).toBe(false)
    })

    it.each([
        ['unknown type', { type: 'telemetry_v2', payload: { metric: 'boot_time_ms', value: 5120 } }],
        ['missing type', { status: 'in_progress', note: 'frame with no type discriminant' }],
        ['notification with non-object body', { type: 'notification', notification: 'oops' }],
    ])('rejects a frame with %s from every envelope guard', (_name, frame) => {
        expect(isNotificationFrame(frame)).toBe(false)
        expect(isTaskRunStateFrame(frame)).toBe(false)
        expect(isKeepaliveFrame(frame)).toBe(false)
        expect(isPermissionRequestFrame(frame)).toBe(false)
    })

    it.each(
        KNOWN_POSTHOG_METHODS.flatMap((method) =>
            NOTIFICATION_PARAMS_BY_METHOD[method].map((params) => [method, params] as const)
        )
    )('%s notifications pass exactly the matching method guard', (method, params) => {
        const wireNotification = notificationOf(notification(method, params))
        for (const known of KNOWN_POSTHOG_METHODS) {
            expect(isPosthogNotification(wireNotification, known)).toBe(known === method)
        }
        expect(isSessionUpdateNotification(wireNotification)).toBe(false)
    })

    it('tolerates the Codex split frames and the Claude combined frame with "has field" checks', () => {
        const [used, usedNullCost, breakdown, combined] = NOTIFICATION_PARAMS_BY_METHOD['_posthog/usage_update'].map(
            (params) => notificationOf(notification('_posthog/usage_update', params))
        )
        for (const wireNotification of [used, usedNullCost]) {
            if (!isPosthogNotification(wireNotification, '_posthog/usage_update')) {
                throw new Error('expected usage_update notification')
            }
            expect(hasUsageUsed(wireNotification.params)).toBe(true)
            expect(hasUsageBreakdown(wireNotification.params)).toBe(false)
            expect(wireNotification.params?.used?.inputTokens).toEqual(expect.any(Number))
        }
        if (!isPosthogNotification(breakdown, '_posthog/usage_update')) {
            throw new Error('expected usage_update notification')
        }
        expect(hasUsageBreakdown(breakdown.params)).toBe(true)
        expect(hasUsageUsed(breakdown.params)).toBe(false)

        // Claude combined frame: both fields present, plus a numeric cost.
        if (!isPosthogNotification(combined, '_posthog/usage_update')) {
            throw new Error('expected usage_update notification')
        }
        expect(hasUsageUsed(combined.params)).toBe(true)
        expect(hasUsageBreakdown(combined.params)).toBe(true)
        expect(combined.params?.cost).toEqual(0.18)
    })

    it('recognizes the session/update-framed usage aggregate', () => {
        expect(isSessionUpdateUsage({ sessionUpdate: 'usage_update', used: 168000, size: 200000 })).toBe(true)
        expect(isKnownSessionUpdate({ sessionUpdate: 'usage_update', used: 168000, size: 200000 })).toBe(false)
        expect(isSessionUpdateUsage({ sessionUpdate: 'agent_message' })).toBe(false)
    })

    it('exposes typed progress params after narrowing', () => {
        const wireNotification = notificationOf(
            notification('_posthog/progress', NOTIFICATION_PARAMS_BY_METHOD['_posthog/progress'][0])
        )
        if (!isPosthogNotification(wireNotification, '_posthog/progress')) {
            throw new Error('expected progress notification')
        }
        expect(wireNotification.params?.label).toEqual('Cloning repository')
        expect(wireNotification.params?.detail).toEqual('PostHog/posthog @ master')
    })

    it.each(SESSION_UPDATE_CASES.map(({ kind, update }) => [kind, update] as const))(
        'narrows a %s session/update to its kind',
        (kind, update) => {
            const wireNotification = notificationOf(sessionUpdate(update))
            expect(isSessionUpdateNotification(wireNotification)).toBe(true)
            const body = isSessionUpdateNotification(wireNotification) ? wireNotification.params?.update : undefined
            expect(isKnownSessionUpdate(body)).toBe(true)
            if (isKnownSessionUpdate(body)) {
                expect(body.sessionUpdate).toBe(kind)
            }
        }
    )

    it('carries the nested _meta.claudeCode denial reason on failed tool_call_update frames', () => {
        const failedCase = SESSION_UPDATE_CASES.find(({ update }) => update.status === 'failed')
        const wireNotification = notificationOf(sessionUpdate(failedCase!.update))
        const body = isSessionUpdateNotification(wireNotification) ? wireNotification.params?.update : undefined
        if (!isKnownSessionUpdate(body) || body.sessionUpdate !== 'tool_call_update') {
            throw new Error('expected a tool_call_update body')
        }
        const toolResponse = body._meta?.claudeCode?.toolResponse as { decisionReason?: string } | undefined
        expect(toolResponse?.decisionReason).toEqual(expect.any(String))
        expect(body._meta?.claudeCode?.toolName).toEqual(expect.any(String))
        expect(body.error?.message).toEqual(expect.any(String))
    })

    it('treats unknown sessionUpdate kinds as session/update of unknown body', () => {
        const wireNotification = notificationOf(
            sessionUpdate({ sessionUpdate: 'plan_delta', entries: [{ content: 'Investigate funnel' }] })
        )
        expect(isSessionUpdateNotification(wireNotification)).toBe(true)
        expect(isKnownSessionUpdate(wireNotification.params?.update)).toBe(false)
    })

    it('matches no known method guard for unknown _posthog methods', () => {
        const wireNotification = notificationOf(notification('_posthog/hologram_sync', { shards: 3 }))
        for (const known of KNOWN_POSTHOG_METHODS) {
            expect(isPosthogNotification(wireNotification, known)).toBe(false)
        }
        expect(isSessionUpdateNotification(wireNotification)).toBe(false)
    })

    it('still classifies degenerate notification bodies as notification frames', () => {
        // Real methods with missing or malformed params must pass the envelope guard — the
        // discriminant-only contract leaves payload defensiveness to the consumers.
        expect(isNotificationFrame(notification('_posthog/turn_complete'))).toBe(true)
        expect(
            isNotificationFrame({
                type: 'notification',
                notification: { method: '_posthog/console', params: 'not-an-object' },
            })
        ).toBe(true)
    })
})
