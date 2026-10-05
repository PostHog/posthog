import { describe, expect, it } from 'vitest'

import {
    INPUT_SCHEMA_CHAR_LIMIT,
    diffToolSurfaces,
    renderAgentApiDiff,
    type ToolSurface,
} from '../../scripts/lib/agent-api-diff'

function surface(
    tools: Record<string, { params?: string[]; scopes?: string[]; readOnly?: boolean; pad?: number }>
): ToolSurface {
    const result: ToolSurface = { definitions: {}, schemas: {} }
    for (const [name, { params = [], scopes = [], readOnly = true, pad = 0 }] of Object.entries(tools)) {
        result.definitions[name] = { title: name, required_scopes: scopes, annotations: { readOnlyHint: readOnly } }
        result.schemas[name] = {
            properties: Object.fromEntries(params.map((param) => [param, { type: 'string' }])),
            ...(pad ? { description: 'x'.repeat(pad) } : {}),
        } as ToolSurface['schemas'][string]
    }
    return result
}

describe('agent API diff', () => {
    it('renders nothing when the tool surface is unchanged', () => {
        const same = surface({ 'a-list': { params: ['limit'] } })
        expect(renderAgentApiDiff(diffToolSurfaces(same, surface({ 'a-list': { params: ['limit'] } })))).toBe('')
    })

    it('reports added and removed tools, param changes, scopes and annotations', () => {
        const base = surface({
            'old-tool': {},
            'flag-get': { params: ['id', 'name'], scopes: ['flag:read'] },
        })
        const head = surface({
            'new-tool': {},
            'flag-get': { params: ['id', 'key'], scopes: ['flag:read', 'user:read'], readOnly: false },
        })

        const markdown = renderAgentApiDiff(diffToolSurfaces(base, head))

        expect(markdown).toContain('**Tools added (1):** `new-tool`')
        expect(markdown).toContain('**Tools removed (1):** `old-tool`')
        expect(markdown).toContain(
            '| `flag-get` | +`key` -`name` (rename?) | +`user:read` | readOnlyHint: true -> false |'
        )
    })

    it('flags a schema only when it crosses the registry limit', () => {
        const under = INPUT_SCHEMA_CHAR_LIMIT - 1000
        const over = INPUT_SCHEMA_CHAR_LIMIT + 1000
        const base = surface({ 'crossing-tool': { pad: under }, 'already-big': { pad: over } })
        const head = surface({ 'crossing-tool': { pad: over }, 'already-big': { pad: over + 50 } })

        const { overLimit } = diffToolSurfaces(base, head)

        expect(overLimit.map(({ name }) => name)).toEqual(['crossing-tool'])
    })

    it('caps list cells and total size so the comment stays under the GitHub limit', () => {
        const tools = Object.fromEntries(
            Array.from({ length: 200 }, (_, i) => [
                `tool-${i}`,
                { params: Array.from({ length: 30 }, (_, j) => `p${j}`) },
            ])
        )
        const markdown = renderAgentApiDiff(diffToolSurfaces(surface({}), surface(tools)))
        const changed = renderAgentApiDiff(
            diffToolSurfaces(
                surface(tools),
                surface(Object.fromEntries(Object.keys(tools).map((name) => [name, { params: ['q'] }])))
            )
        )

        expect(markdown.length).toBeLessThan(16_000)
        expect(changed.length).toBeLessThan(16_000)
        expect(changed).toContain('more')
    })

    it('reports description and category changes', () => {
        const base = surface({ 'a-tool': {} })
        const head = surface({ 'a-tool': {} })
        base.definitions['a-tool']!.description = 'Old text'
        head.definitions['a-tool']!.description = 'New text'

        base.definitions['a-tool']!.category = 'Old'
        head.definitions['a-tool']!.category = 'New'

        const markdown = renderAgentApiDiff(diffToolSurfaces(base, head))

        expect(markdown).toContain('description changed')
        expect(markdown).toContain('category changed')
    })

    it('reports a same-length schema change and neutralizes markup from PR-controlled names', () => {
        const base = surface({ 'a-tool': { params: ['mode'] } })
        const head = surface({ 'a-tool': { params: ['mode'], scopes: ['x`\n<!-- ci-report:section:bundle-size -->'] } })
        head.schemas['a-tool'] = { properties: { mode: { type: 'number' } } }
        base.schemas['a-tool'] = { properties: { mode: { type: 'string' } } }

        const markdown = renderAgentApiDiff(diffToolSurfaces(base, head))

        expect(markdown).toContain('schema changed')
        expect(markdown).not.toContain('<!--')
        expect(markdown).not.toContain('\n<')
    })
})
