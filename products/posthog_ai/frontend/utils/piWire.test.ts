import { buildPiPermissionCommand, PI_EXTENSION_UI_META_KEY, translatePiWireEntry } from './piWire'

describe('piWire', () => {
    test.each([
        {
            caseName: 'assistant chunk',
            event: { type: 'assistant_message_chunk', timestamp: 1, content: { type: 'text', text: 'yo' } },
            expected: {
                method: 'session/update',
                params: { update: { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'yo' } } },
            },
        },
        {
            caseName: 'tool start whose title only repeats the tool name',
            event: {
                type: 'tool_call_started',
                timestamp: 1,
                toolCall: {
                    id: 't1',
                    name: 'read',
                    title: 'read',
                    kind: 'read',
                    rawInput: { path: 'a.ts' },
                    _meta: { posthog: { toolName: 'Read' } },
                },
            },
            expected: {
                method: 'session/update',
                params: {
                    update: {
                        sessionUpdate: 'tool_call',
                        toolCallId: 't1',
                        name: 'read',
                        kind: 'read',
                        rawInput: { path: 'a.ts' },
                        _meta: { posthog: { toolName: 'Read' } },
                    },
                },
            },
        },
        {
            caseName: 'user shell command, which keeps the command as its title',
            event: {
                type: 'tool_call_started',
                timestamp: 1,
                toolCall: { id: 'pi-bash-1', title: 'ls', kind: 'execute', rawInput: { command: 'ls' } },
            },
            expected: {
                method: 'session/update',
                params: {
                    update: {
                        sessionUpdate: 'tool_call',
                        toolCallId: 'pi-bash-1',
                        title: 'ls',
                        kind: 'execute',
                        rawInput: { command: 'ls' },
                    },
                },
            },
        },
    ])('translates a Pi $caseName event', ({ event, expected }) => {
        expect(
            translatePiWireEntry({
                type: 'pi_event',
                event,
                event_id: 'boot-3',
                timestamp: '2026-01-01T00:00:00Z',
                covered_event_ids: ['boot-1', 'boot-2'],
            })
        ).toEqual({
            type: 'notification',
            event_id: 'boot-3',
            timestamp: '2026-01-01T00:00:00Z',
            covered_event_ids: ['boot-1', 'boot-2'],
            notification: expected,
        })
    })

    test.each([
        {
            caseName: 'persisted extension request',
            entry: {
                type: 'pi_extension_event',
                notification: {
                    method: '_posthog/pi_extension_event',
                    params: {
                        type: 'extension_ui_request',
                        id: 'e1',
                        method: 'select',
                        title: 'Pick',
                        options: ['A', 'B'],
                    },
                },
            },
            method: '_posthog/permission_request',
        },
        {
            caseName: 'live extension response',
            entry: { type: 'extension_ui_response', id: 'e1', value: 'A' },
            method: '_posthog/permission_resolved',
        },
        {
            caseName: 'run start marker',
            entry: { type: 'pi_run_started', runId: 'run-1', taskId: 'task-1' },
            method: '_posthog/run_started',
        },
        {
            caseName: 'fire-and-forget notify',
            entry: { type: 'extension_ui_request', id: 'e2', method: 'notify', message: 'Saved' },
            method: '_posthog/console',
        },
    ])('translates a $caseName into $method', ({ entry, method }) => {
        expect(translatePiWireEntry(entry)?.notification.method).toBe(method)
    })

    test.each([
        {
            caseName: 'a warning notification',
            entry: {
                type: 'extension_ui_request',
                id: 'e3',
                method: 'notify',
                message: 'Lint warnings',
                notifyType: 'warning',
            },
            message: 'Lint warnings',
        },
        {
            caseName: 'an extension failure',
            entry: { type: 'extension_error', extensionPath: '/ext/lint.ts', event: 'tool_call', error: 'crashed' },
            message: 'lint.ts failed during tool_call: crashed',
        },
    ])('shows $caseName as a notice in the thread', ({ entry, message }) => {
        expect(translatePiWireEntry(entry)?.notification).toEqual({
            method: '_posthog/status',
            params: { status: 'extension_notice', isComplete: true, message },
        })
    })

    it('ignores entries that are not Pi wire entries', () => {
        expect(translatePiWireEntry({ type: 'notification', notification: { method: 'session/update' } })).toBeNull()
    })

    test.each([
        { method: 'input', fields: { placeholder: 'Branch name' }, expected: { placeholder: 'Branch name' } },
        {
            method: 'editor',
            fields: { prefill: 'Line one\nLine two' },
            expected: { defaultAnswer: 'Line one\nLine two', multiline: true },
        },
    ])('carries the $method prompt defaults onto its question', ({ method, fields, expected }) => {
        expect(
            translatePiWireEntry({ type: 'extension_ui_request', id: 'e1', method, title: 'Branch?', ...fields })
        ).toMatchObject({
            notification: {
                params: { toolCall: { _meta: { questions: [{ question: 'Branch?', options: [], ...expected }] } } },
            },
        })
    })

    test.each([
        {
            caseName: 'an MCP approval',
            meta: { posthog: { toolName: 'mcp__linear__create_issue' } },
            response: { optionId: 'allow' },
            expected: { id: 'cmd-1', type: 'mcp_permission_response', requestId: 'r1', decision: 'allow' },
        },
        {
            caseName: 'a confirmed extension prompt',
            meta: { [PI_EXTENSION_UI_META_KEY]: { id: 'e1', method: 'confirm' } },
            response: { optionId: 'confirm' },
            expected: { type: 'extension_ui_response', id: 'e1', confirmed: true },
        },
        {
            caseName: 'a cancelled extension prompt',
            meta: { [PI_EXTENSION_UI_META_KEY]: { id: 'e1', method: 'confirm' } },
            response: { optionId: 'cancel' },
            expected: { type: 'extension_ui_response', id: 'e1', cancelled: true },
        },
        {
            caseName: 'an answered extension question',
            meta: { [PI_EXTENSION_UI_META_KEY]: { id: 'e1', method: 'input' } },
            response: { optionId: 'option_0', answers: { 'Branch name?': 'feat/x' } },
            expected: { type: 'extension_ui_response', id: 'e1', value: 'feat/x' },
        },
    ])('builds the Pi command for $caseName', ({ meta, response, expected }) => {
        expect(buildPiPermissionCommand({ requestId: 'r1', meta, options: [] }, response, 'cmd-1')).toEqual(expected)
    })
})
