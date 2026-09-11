import fs from 'fs'
import path from 'path'

import { toolRegistry } from 'products/posthog_ai/frontend/api/tools'

// Every metrics tool the MCP codegen emits, so a tool added to the catalog without a registry entry
// fails here instead of shipping the generic wrench card. Read off the generated file rather than
// imported, to keep the services/mcp graph out of a frontend test.
function generatedMetricsToolNames(): string[] {
    const generated = path.resolve(__dirname, '../../../services/mcp/src/tools/generated/metrics.ts')
    const source = fs.readFileSync(generated, 'utf-8')
    const names = [...source.matchAll(/name: '([a-z0-9-]+)'/g)].map((m) => m[1])
    if (names.length === 0) {
        throw new Error(`No tool names found in ${generated} — the codegen output moved or changed shape`)
    }
    return [...new Set(names)].sort()
}

describe('posthogAiToolRenderers', () => {
    it.each(generatedMetricsToolNames())('claims %s in the shared registry', (key) => {
        expect(toolRegistry.lookup(key)).not.toBeNull()
    })

    it('gives query-metrics the custom card and leaves the rest on the generic one', () => {
        expect(toolRegistry.lookup('query-metrics')?.Renderer).not.toBeUndefined()
        expect(toolRegistry.lookup('metric-names-list')?.Renderer).toBeUndefined()
        expect(toolRegistry.lookup('metric-names-list')?.displayName).toEqual('List metrics')
    })
})
