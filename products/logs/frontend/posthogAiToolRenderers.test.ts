import fs from 'fs'
import path from 'path'

import { toolRegistry } from 'products/posthog_ai/frontend/api/tools'

// Every logs tool the MCP codegen emits, so a tool added to the catalog without a registry entry
// fails here instead of shipping the generic wrench card. Read off the generated file rather than
// imported, to keep the services/mcp graph out of a frontend test.
function generatedLogsToolNames(): string[] {
    const generated = path.resolve(__dirname, '../../../services/mcp/src/tools/generated/logs.ts')
    const source = fs.readFileSync(generated, 'utf-8')
    const names = [...source.matchAll(/name: '([a-z0-9-]+)'/g)].map((m) => m[1])
    if (names.length === 0) {
        throw new Error(`No tool names found in ${generated} — the codegen output moved or changed shape`)
    }
    return [...new Set(names)].sort()
}

describe('posthogAiToolRenderers', () => {
    it.each(generatedLogsToolNames())('claims %s in the shared registry', (key) => {
        expect(toolRegistry.lookup(key)).not.toBeNull()
    })

    it('gives query-logs the custom card and leaves the rest on the generic one', () => {
        expect(toolRegistry.lookup('query-logs')?.Renderer).not.toBeUndefined()
        expect(toolRegistry.lookup('logs-patterns')?.Renderer).toBeUndefined()
        expect(toolRegistry.lookup('logs-patterns')?.displayName).toEqual('Log patterns')
    })
})
