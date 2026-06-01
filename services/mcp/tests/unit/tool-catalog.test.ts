import { beforeEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { ToolCatalog } from '@/hono/tool-catalog'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

type FakeDefinition = {
    title: string
    description: string
    feature: string
    category: string
    required_scopes: string[]
    annotations: {
        destructiveHint: boolean
        idempotentHint: boolean
        openWorldHint: boolean
        readOnlyHint: boolean
    }
    [key: string]: unknown
}

function makeToolBase(name: string, overrides?: Partial<ToolBase<ZodObjectAny>>): ToolBase<ZodObjectAny> {
    return {
        name,
        schema: z.object({}),
        handler: vi.fn(),
        ...overrides,
    }
}

const fakeDef = (overrides?: Record<string, unknown>): FakeDefinition => ({
    title: 'Title',
    description: 'Desc',
    feature: 'general',
    category: 'general',
    required_scopes: [] as string[],
    annotations: {
        destructiveHint: false,
        idempotentHint: false,
        openWorldHint: false,
        readOnlyHint: false,
    },
    ...overrides,
})

vi.mock('@/tools', () => ({
    TOOL_MAP: {
        'tool-a': () => makeToolBase('tool-a'),
        'tool-b': () => makeToolBase('tool-b'),
    },
}))

vi.mock('@/tools/generated', () => ({
    GENERATED_TOOL_MAP: {
        'gen-tool-c': () => makeToolBase('gen-tool-c'),
    },
}))

const DEFINITIONS: Record<string, FakeDefinition> = {
    'tool-a': fakeDef({ required_scopes: ['project:read'] }),
    'tool-b': fakeDef({ feature: 'insights', annotations: { ...fakeDef().annotations, readOnlyHint: true } }),
    'gen-tool-c': fakeDef({ required_scopes: ['action:write'] }),
}

vi.mock('@/tools/toolDefinitions', () => ({
    getToolDefinitions: () => DEFINITIONS,
    getToolDefinition: (name: string) => {
        const def = DEFINITIONS[name]
        if (!def) {
            throw new Error(`Tool definition not found for: ${name}`)
        }
        return def
    },
    getToolsForFeatures: (options?: {
        features?: string[]
        tools?: string[]
        readOnly?: boolean
        aiConsentGiven?: boolean
        featureFlags?: Record<string, boolean>
    }) => {
        let names = Object.keys(DEFINITIONS)
        if (options?.features?.length) {
            names = names.filter((n) => {
                const def = DEFINITIONS[n]
                return def && options.features!.includes(def.feature as string)
            })
        }
        if (options?.readOnly) {
            names = names.filter((n) => {
                const def = DEFINITIONS[n]
                return def?.annotations.readOnlyHint === true
            })
        }
        return names
    },
}))

describe('ToolCatalog', () => {
    let catalog: ToolCatalog

    beforeEach(async () => {
        catalog = new ToolCatalog()
    })

    describe('warmup', () => {
        it('should import tool modules and build the pre-computed map', async () => {
            expect(catalog.warmedUp).toBe(false)
            await catalog.warmup()
            expect(catalog.warmedUp).toBe(true)
        })

        it('should be idempotent', async () => {
            await catalog.warmup()
            await catalog.warmup()
            expect(catalog.warmedUp).toBe(true)
        })
    })

    describe('getFilteredTools', () => {
        beforeEach(async () => {
            await catalog.warmup()
        })

        it('should return all tools when no filters applied', () => {
            const tools = catalog.getFilteredTools({ scopes: ['project:read', 'action:write'] })
            const names = tools.map((t) => t.name).sort()
            expect(names).toEqual(['gen-tool-c', 'tool-a', 'tool-b'])
        })

        it('should exclude tools by name', () => {
            const tools = catalog.getFilteredTools({
                scopes: ['project:read', 'action:write'],
                excludeTools: ['tool-b'],
            })
            const names = tools.map((t) => t.name).sort()
            expect(names).toEqual(['gen-tool-c', 'tool-a'])
        })

        it('should filter by scopes', () => {
            const tools = catalog.getFilteredTools({ scopes: ['project:read'] })
            const names = tools.map((t) => t.name).sort()
            expect(names).toEqual(['tool-a', 'tool-b'])
        })

        it('should exclude tools when scopes are missing', () => {
            const tools = catalog.getFilteredTools({ scopes: [] })
            const names = tools.map((t) => t.name)
            expect(names).toEqual(['tool-b'])
        })

        it('should filter by readOnly when passed through to getToolsForFeatures', () => {
            const tools = catalog.getFilteredTools({
                scopes: ['project:read', 'action:write'],
                readOnly: true,
            })
            const names = tools.map((t) => t.name)
            expect(names).toEqual(['tool-b'])
        })

        it('should filter by features when passed through to getToolsForFeatures', () => {
            const tools = catalog.getFilteredTools({
                scopes: ['project:read'],
                features: ['insights'],
            })
            const names = tools.map((t) => t.name)
            expect(names).toEqual(['tool-b'])
        })

        it('should merge title and description from definitions onto the tool', () => {
            const tools = catalog.getFilteredTools({ scopes: ['project:read'] })
            const toolA = tools.find((t) => t.name === 'tool-a')
            expect(toolA).toBeTruthy()
            expect(toolA!.title).toBe('Title')
            expect(toolA!.description).toBe('Desc')
        })

        it('should attach scopes and annotations from definitions', () => {
            const tools = catalog.getFilteredTools({ scopes: ['project:read'] })
            const toolA = tools.find((t) => t.name === 'tool-a')
            expect(toolA!.scopes).toEqual(['project:read'])
            expect(toolA!.annotations).toEqual(expect.objectContaining({ readOnlyHint: false }))
        })

        it('should return empty array when catalog is not warmed up', () => {
            const coldCatalog = new ToolCatalog()
            const tools = coldCatalog.getFilteredTools({ scopes: [] })
            expect(tools).toEqual([])
        })
    })
})
