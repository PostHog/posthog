import { MCP_MESSAGE_FIELD_LIMITS } from 'scenes/hog-functions/sub-templates/sub-templates'

import { parseExampleRows } from './mcpNotificationExamplesLogic'

// Rows arrive positionally: [use_case, client_name, server_name, intent, tool_name]. The query
// derives use_case, since the failure use cases all share the $mcp_tool_call event.
const MISSING_CAPABILITY_ROW = ['missing-capability', 'Cursor', 'acme-mcp', 'export to PDF', '']
const TOOL_ERROR_ROW = ['tool-error', 'Claude Code', 'acme-mcp', 'why did signups drop', 'query-events']

describe('parseExampleRows', () => {
    it('maps each use case from its positional columns', () => {
        expect(parseExampleRows([MISSING_CAPABILITY_ROW, TOOL_ERROR_ROW])).toEqual({
            'missing-capability': {
                clientName: 'Cursor',
                serverName: 'acme-mcp',
                intent: 'export to PDF',
                toolName: '',
            },
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
        ['missing intent', ['missing-capability', 'Cursor', 'acme-mcp', '', '']],
        ['missing client name', ['missing-capability', null, 'acme-mcp', 'export to PDF', '']],
        ['a failure with no tool name', ['auth-error', 'Claude Code', 'acme-mcp', 'why', '']],
        ['an unrecognized use case', ['something-else', 'Cursor', 'acme-mcp', 'export to PDF', 'query-events']],
    ])('drops a row with %s', (_label, row) => {
        expect(parseExampleRows([row])).toEqual({})
    })

    it('cuts a field at the limit the delivered message uses', () => {
        const intent = 'x'.repeat(MCP_MESSAGE_FIELD_LIMITS.intent + 50)

        const parsed = parseExampleRows([['missing-capability', 'Cursor', 'acme-mcp', intent, '']])

        expect(parsed['missing-capability']?.intent).toHaveLength(MCP_MESSAGE_FIELD_LIMITS.intent)
    })
})
