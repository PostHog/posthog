import { describe, expect, it } from 'vitest'

import { builtInAgentToolsToExclude } from '@/hono/request-state-resolver'

describe('builtInAgentToolsToExclude', () => {
    const cases = [
        {
            description: 'excludes nothing for a member token',
            scopes: ['project:read', 'insight:read'],
            expected: [],
        },
        {
            // The regression guard: Django answers these two with 403 on every
            // built-in agent call, so advertising them only burns the agent's turn.
            description: 'excludes the MCP Store member tools for a built-in agent token',
            scopes: ['project:read', 'mcp_builtin_agent:read'],
            expected: ['mcp-connections-list', 'mcp-connection-tools-list'],
        },
        {
            // The scope is server-minted, so a user-consented wildcard never stands in for it.
            description: 'excludes nothing for a wildcard token',
            scopes: ['*'],
            expected: [],
        },
    ]

    it.each(cases)('$description', ({ scopes, expected }) => {
        expect(builtInAgentToolsToExclude(scopes)).toEqual(expected)
    })
})
