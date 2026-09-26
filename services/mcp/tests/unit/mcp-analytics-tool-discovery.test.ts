import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/mcp_analytics'

// Agents ask for the ranked list of tools through a single-tool tool, with no
// tool name and often a `limit` the schema does not declare. The list tool
// serves that shape; the detail tools must keep rejecting it.
describe('mcp analytics tool discovery', () => {
    const listSchema = GENERATED_TOOLS['query-mcp-tools']!().schema

    it.each([
        ['no parameters', {}],
        ['a page size', { limit: 10 }],
        ['a search and a sort', { search: 'query-mcp', sortColumn: 'error_rate_pct', sortDirection: 'ASC' }],
    ])('query-mcp-tools accepts %s', (_label, input) => {
        expect(listSchema.safeParse(input).success).toBe(true)
    })

    describe.each([['query-mcp-tool-stats'], ['query-mcp-tool-daily-stats'], ['query-mcp-tool-failures']])(
        '%s still needs toolName',
        (toolName) => {
            const schema = GENERATED_TOOLS[toolName]!().schema

            it.each([
                ['a call with no parameters', {}],
                ['a call that pages instead of naming a tool', { limit: 10 }],
                ['a snake_case tool name', { tool_name: 'query-trends' }],
            ])('rejects %s', (_label, input) => {
                expect(schema.safeParse(input).success).toBe(false)
            })

            it('accepts the tool name', () => {
                expect(schema.safeParse({ toolName: 'query-trends' }).success).toBe(true)
            })
        }
    )
})
