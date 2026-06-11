import { describe, expect, it } from 'vitest'

import { parseFrame } from './acp-parse'
import type { HarnessFrame } from './contract'

// Frames below are verbatim shapes captured from the real @posthog/agent
// server running in the published image (see plan §11). This keeps the parser
// honest against reality without needing a container.
describe('parseFrame', () => {
    it('maps the connected frame', () => {
        expect(parseFrame({ type: 'connected', run_id: 'r' })).toEqual({ kind: 'connected' })
    })

    it('maps _posthog lifecycle frames', () => {
        const f = (method: string, params: unknown): HarnessFrame => ({
            type: 'notification',
            notification: { jsonrpc: '2.0', method, params },
        })
        expect(parseFrame(f('_posthog/run_started', {}))).toEqual({ kind: 'run_started' })
        expect(parseFrame(f('_posthog/turn_complete', {}))).toEqual({ kind: 'turn_complete' })
        expect(parseFrame(f('_posthog/task_complete', { ok: true }))).toMatchObject({ kind: 'task_complete' })
        expect(parseFrame(f('_posthog/console', { level: 'debug', message: 'hi' }))).toEqual({
            kind: 'log',
            level: 'debug',
            message: 'hi',
        })
    })

    it('maps agent thought + message chunks', () => {
        const su = (update: unknown): HarnessFrame => ({
            type: 'notification',
            notification: { jsonrpc: '2.0', method: 'session/update', params: { sessionId: 's', update } },
        })
        expect(
            parseFrame(su({ sessionUpdate: 'agent_thought_chunk', content: { type: 'text', text: 'The' } }))
        ).toEqual({
            kind: 'thought',
            text: 'The',
        })
        expect(parseFrame(su({ sessionUpdate: 'agent_message_chunk', content: { text: 'hello' } }))).toEqual({
            kind: 'assistant_text',
            text: 'hello',
        })
    })

    it('maps a real Bash tool_call_update with its command', () => {
        const frame: HarnessFrame = {
            type: 'notification',
            notification: {
                jsonrpc: '2.0',
                method: 'session/update',
                params: {
                    sessionId: 's',
                    update: {
                        sessionUpdate: 'tool_call_update',
                        toolCallId: 'toolu_01C4',
                        _meta: { claudeCode: { toolName: 'Bash', bashCommand: 'ls /tmp/workspace' } },
                    },
                },
            },
        }
        expect(parseFrame(frame)).toEqual({
            kind: 'tool_call',
            toolCallId: 'toolu_01C4',
            tool: 'Bash',
            command: 'ls /tmp/workspace',
            title: undefined,
        })
    })

    it('maps a completed tool_call_update to a tool_result with its output', () => {
        const frame: HarnessFrame = {
            type: 'notification',
            notification: {
                jsonrpc: '2.0',
                method: 'session/update',
                params: {
                    update: {
                        sessionUpdate: 'tool_call_update',
                        toolCallId: 'toolu_01C4',
                        status: 'completed',
                        rawOutput: { stdout: 'captured-hello', stderr: '', isError: false },
                        content: [
                            { type: 'content', content: { type: 'text', text: '```console\ncaptured-hello\n```' } },
                        ],
                    },
                },
            },
        }
        expect(parseFrame(frame)).toEqual({
            kind: 'tool_result',
            toolCallId: 'toolu_01C4',
            ok: true,
            output: 'captured-hello',
        })
    })

    it('marks a failed tool_call_update as not ok', () => {
        const frame: HarnessFrame = {
            type: 'notification',
            notification: {
                jsonrpc: '2.0',
                method: 'session/update',
                params: {
                    update: {
                        sessionUpdate: 'tool_call_update',
                        toolCallId: 't1',
                        status: 'completed',
                        rawOutput: { stdout: '', stderr: 'no such file', isError: true },
                    },
                },
            },
        }
        expect(parseFrame(frame)).toMatchObject({
            kind: 'tool_result',
            toolCallId: 't1',
            ok: false,
            output: 'no such file',
        })
    })

    it('ignores intermediate tool_call_update arg-streaming frames', () => {
        const frame: HarnessFrame = {
            type: 'notification',
            notification: {
                jsonrpc: '2.0',
                method: 'session/update',
                params: {
                    update: { sessionUpdate: 'tool_call_update', toolCallId: 't1', rawInput: { command: 'ech' } },
                },
            },
        }
        expect(parseFrame(frame)).toBeNull()
    })

    it('maps the rich _posthog/usage_update (tokens + cache + cost)', () => {
        const frame: HarnessFrame = {
            type: 'notification',
            notification: {
                jsonrpc: '2.0',
                method: '_posthog/usage_update',
                params: {
                    used: { inputTokens: 4, outputTokens: 116, cachedReadTokens: 52080, cachedWriteTokens: 17597 },
                    cost: 0.08491875,
                },
            },
        }
        expect(parseFrame(frame)).toEqual({
            kind: 'usage',
            inputTokens: 4,
            outputTokens: 116,
            cacheRead: 52080,
            cacheWrite: 17597,
            costUsd: 0.08491875,
        })
    })

    it('maps a permission_request frame to options', () => {
        const frame: HarnessFrame = {
            type: 'permission_request',
            requestId: 'req-1',
            options: [
                { optionId: 'allow', name: 'Allow', kind: 'allow_once' },
                { optionId: 'reject', name: 'Reject', kind: 'reject_once' },
            ],
            toolCall: { _meta: { claudeCode: { toolName: 'Bash' } } },
        }
        expect(parseFrame(frame)).toMatchObject({
            kind: 'permission_request',
            requestId: 'req-1',
            tool: 'Bash',
            options: [{ optionId: 'allow' }, { optionId: 'reject' }],
        })
    })

    it('surfaces a notification-level JSON-RPC error', () => {
        const frame: HarnessFrame = {
            type: 'notification',
            notification: {
                jsonrpc: '2.0',
                id: 2,
                method: 'session/prompt',
                error: { code: -32603, message: 'API Error: 400 unknown model' },
            },
        }
        expect(parseFrame(frame)).toEqual({ kind: 'error', message: 'API Error: 400 unknown model' })
    })

    it('ignores echo / noise frames', () => {
        const su = (update: unknown): HarnessFrame => ({
            type: 'notification',
            notification: { jsonrpc: '2.0', method: 'session/update', params: { update } },
        })
        expect(parseFrame(su({ sessionUpdate: 'user_message_chunk', content: { text: 'x' } }))).toBeNull()
        expect(parseFrame(su({ sessionUpdate: 'available_commands_update', availableCommands: [] }))).toBeNull()
    })
})
