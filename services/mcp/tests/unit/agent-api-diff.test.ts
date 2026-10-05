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
})
