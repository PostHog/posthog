import type { AcpMessage } from '../conversation/acp-types'
import { derivePendingPermissions } from './permissions'

function requestEvent(requestId: string, ts = 1): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: {
            jsonrpc: '2.0',
            method: '_posthog/permission_request',
            params: {
                requestId,
                toolCall: { toolCallId: `tc-${requestId}`, title: 'Run command', kind: 'execute' },
                options: [
                    { optionId: 'allow_once', name: 'Allow', kind: 'allow_once' },
                    { optionId: 'reject_once', name: 'Reject', kind: 'reject_once' },
                ],
            },
        },
    }
}

function resolvedEvent(requestId: string, ts = 2): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: { jsonrpc: '2.0', method: '_posthog/permission_resolved', params: { requestId } },
    }
}

describe('derivePendingPermissions', () => {
    it('returns [] with no permission events', () => {
        expect(derivePendingPermissions([])).toEqual([])
    })

    it('surfaces an unresolved permission request', () => {
        const pending = derivePendingPermissions([requestEvent('r1')])
        expect(pending).toHaveLength(1)
        expect(pending[0].requestId).toBe('r1')
        expect(pending[0].options).toHaveLength(2)
        expect(pending[0].toolCall.toolCallId).toBe('tc-r1')
    })

    it('drops a request once it is resolved', () => {
        expect(derivePendingPermissions([requestEvent('r1', 1), resolvedEvent('r1', 2)])).toEqual([])
    })

    it('keeps other requests pending when one resolves', () => {
        const pending = derivePendingPermissions([requestEvent('r1', 1), requestEvent('r2', 2), resolvedEvent('r1', 3)])
        expect(pending.map((p) => p.requestId)).toEqual(['r2'])
    })

    it('ignores malformed requests (missing options)', () => {
        const malformed: AcpMessage = {
            type: 'acp_message',
            ts: 1,
            message: {
                jsonrpc: '2.0',
                method: '_posthog/permission_request',
                params: { requestId: 'bad', toolCall: { toolCallId: 'tc', title: 'x' }, options: [] },
            },
        }
        expect(derivePendingPermissions([malformed])).toEqual([])
    })

    it('records receivedAt from the event timestamp', () => {
        const pending = derivePendingPermissions([requestEvent('r1', 1234)])
        expect(pending[0].receivedAt).toBe(1234)
    })
})
