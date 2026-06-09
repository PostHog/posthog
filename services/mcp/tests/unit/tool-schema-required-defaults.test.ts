import { describe, expect, it } from 'vitest'

import { ToolCatalog } from '@/hono/tool-catalog'

// Walks a converted JSON Schema and collects every property that carries a `default`
// yet is still listed in its object's `required` array. By JSON-Schema convention a
// defaulted field is omittable, so this set must always be empty. This guards the
// entire MCP tool surface against the conversion mode ever flipping to output (which
// would promote defaulted fields into `required` and inflate every call).
function findDefaultedRequired(node: unknown, path: string, violations: string[]): void {
    if (Array.isArray(node)) {
        node.forEach((item, i) => findDefaultedRequired(item, `${path}[${i}]`, violations))
        return
    }
    if (!node || typeof node !== 'object') {
        return
    }
    const obj = node as Record<string, unknown>
    const properties = obj['properties']
    const required = obj['required']
    if (properties && typeof properties === 'object' && Array.isArray(required)) {
        const props = properties as Record<string, unknown>
        for (const name of required) {
            if (typeof name !== 'string') {
                continue
            }
            const prop = props[name]
            if (prop && typeof prop === 'object' && 'default' in (prop as Record<string, unknown>)) {
                violations.push(`${path}.${name}`)
            }
        }
    }
    for (const [key, value] of Object.entries(obj)) {
        findDefaultedRequired(value, `${path}.${key}`, violations)
    }
}

describe('Tool input schemas — defaulted fields are not required', () => {
    it('never lists a property carrying a `default` in `required`', async () => {
        const catalog = new ToolCatalog()
        await catalog.warmup()

        const entries = catalog.getPreBuiltEntries()
        expect(entries.length).toBeGreaterThan(0)

        const violations: string[] = []
        for (const entry of entries) {
            findDefaultedRequired(entry.inputSchema, entry.name, violations)
        }

        expect(violations).toEqual([])
    })
})
