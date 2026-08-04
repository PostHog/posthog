import { MCP_MESSAGE_FIELD_LIMITS } from 'scenes/hog-functions/sub-templates/sub-templates'

import { parseExampleRows } from './mcpNotificationExamplesLogic'

// Rows arrive positionally: [use_case, client_name, server_name, intent, tool_name]. The query
// derives use_case, since the failure use cases all share the $mcp_tool_call event.
const TOOL_ERROR_ROW = ['tool-error', 'Claude Code', 'acme-mcp', 'why did signups drop', 'query-events']

describe('parseExampleRows', () => {
    it('maps a failure example from its positional columns', () => {
        expect(parseExampleRows([TOOL_ERROR_ROW])).toEqual({
            'tool-error': {
                clientName: 'Claude Code',
                serverName: 'acme-mcp',
                intent: 'why did signups drop',
                toolName: 'query-events',
            },
        })
    })

    // A half-real example (project's client name, our invented intent) reads as genuine but isn't,
    // so an incomplete row is dropped in favour of the honest sample copy.
    it.each([
        ['missing intent', ['tool-error', 'Claude Code', 'acme-mcp', '', 'query-events']],
        ['missing client name', ['tool-error', null, 'acme-mcp', 'why', 'query-events']],
        ['no tool name', ['tool-error', 'Claude Code', 'acme-mcp', 'why', '']],
        ['an unrecognized use case', ['something-else', 'Cursor', 'acme-mcp', 'why', 'query-events']],
    ])('drops a row with %s', (_label, row) => {
        expect(parseExampleRows([row])).toEqual({})
    })

    it('cuts a field at the limit the delivered message uses', () => {
        const intent = 'x'.repeat(MCP_MESSAGE_FIELD_LIMITS.intent + 50)

        const parsed = parseExampleRows([['tool-error', 'Cursor', 'acme-mcp', intent, 'query-events']])

        expect(parsed['tool-error']?.intent).toHaveLength(MCP_MESSAGE_FIELD_LIMITS.intent)
    })
})
