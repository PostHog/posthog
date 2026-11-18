import { describe, expect, it } from 'vitest'

import { buildCliCatalog } from '@/cli/catalog/build'
import { catalogTool } from '@/cli/catalog/executor'
import { loadCatalog } from '@/cli/catalog/load'
import { findIgnoredInputKeys } from '@/lib/ignored-input-keys'
import { readParamAliases } from '@/tools/cast-helpers'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

type Json = Record<string, any>

const UUID = '01234567-89ab-4cde-8f01-23456789abcd'

interface SampleOptions {
    full: boolean
    asText?: boolean
    offsetDatetimes?: boolean
    unknownKeys?: boolean
}

function sample(node: Json | undefined, options: SampleOptions, root: Json, depth = 0): unknown {
    const { full, asText = false } = options
    if (!node || depth > 6) {
        return undefined
    }
    if (node.$ref) {
        const name = String(node.$ref).split('/').pop()!
        return sample(root.$defs?.[name] ?? root.definitions?.[name], options, root, depth + 1)
    }
    if ('const' in node) {
        return node.const
    }
    if (node.enum) {
        return node.enum.find((value: unknown) => value !== null) ?? node.enum[0]
    }
    if (node.default !== undefined) {
        return node.default
    }
    const variants = node.anyOf ?? node.oneOf
    if (variants) {
        const usable = variants.filter((variant: Json) => variant.type !== 'null')
        return sample(usable[0] ?? variants[0], options, root, depth + 1)
    }
    if (node.allOf) {
        return sample(Object.assign({}, ...node.allOf), options, root, depth + 1)
    }
    const type = Array.isArray(node.type) ? node.type.find((t: string) => t !== 'null') : node.type
    switch (type) {
        case 'string':
            return sampleString(node, options)
        case 'integer': {
            const value = typeof node.minimum === 'number' ? Math.max(node.minimum, 7) : 7
            return asText ? String(value) : value
        }
        case 'number': {
            const value = typeof node.minimum === 'number' ? Math.max(node.minimum, 7.5) : 7.5
            return asText ? String(value) : value
        }
        case 'boolean':
            return asText ? 'true' : true
        case 'array': {
            const item = sample(node.items, options, root, depth + 1)
            const count = Math.max(node.minItems ?? 1, 1)
            return item === undefined ? [] : Array.from({ length: count }, () => item)
        }
        case 'object':
        case undefined: {
            if (!node.properties) {
                return type === 'object' ? {} : undefined
            }
            const required = new Set<string>(node.required ?? [])
            const value: Json = options.unknownKeys ? { not_a_param: 'sample-value' } : {}
            for (const [key, child] of Object.entries<Json>(node.properties)) {
                if (full || required.has(key)) {
                    const childValue = sample(child, options, root, depth + 1)
                    if (childValue !== undefined) {
                        value[key] = childValue
                    }
                }
            }
            return value
        }
        default:
            return undefined
    }
}

function sampleString(node: Json, options: SampleOptions): string {
    switch (node.format) {
        case 'uuid':
            return UUID
        case 'date-time':
            return options.offsetDatetimes ? '2026-01-02T03:04:05+01:00' : '2026-01-02T03:04:05Z'
        case 'date':
            return '2026-01-02'
        case 'time':
            return '03:04:05'
        case 'email':
            return 'person@example.com'
        case 'uri':
        case 'url':
            return 'https://example.com/path'
    }
    const base = 'sample-value'
    const min = node.minLength ?? 0
    const value = base.length >= min ? base : base.padEnd(min, 'x')
    return typeof node.maxLength === 'number' ? value.slice(0, Math.max(node.maxLength, 1)) : value
}

interface Recorded {
    calls: { method: string; args: unknown }[]
}

function fakeContext(): { context: Context; recorded: Recorded } {
    const recorded: Recorded = { calls: [] }
    const page = { id: 42, short_id: 'abc', results: [{ id: 1, short_id: 'x', name: 'one' }], next: null }
    const api: any = new Proxy(
        {},
        {
            get(_target, property: string) {
                if (property === 'getProjectBaseUrl') {
                    return (projectId: unknown) => `https://us.posthog.com/project/${projectId}`
                }
                if (property === 'then') {
                    return undefined
                }
                return (...args: unknown[]) => {
                    recorded.calls.push({ method: property, args: JSON.parse(JSON.stringify(args)) })
                    return Promise.resolve(structuredClone(page))
                }
            },
        }
    )
    const stateManager: any = {
        getProjectId: async () => '7',
        getOrgID: async () => 'org-1',
        getDistinctId: async () => 'distinct-1',
        getApiKey: async () => ({ scopes: ['*'] }),
    }
    const context = { api, stateManager, env: {}, cache: {}, trackEvent: async () => {} } as unknown as Context
    return { context, recorded }
}

interface Outcome {
    parsed: boolean
    data?: unknown
    ignoredKeys?: string[]
    calls?: Recorded['calls']
    error?: string
}

async function run(tool: ToolBase<ZodObjectAny>, input: unknown): Promise<Outcome> {
    const parsed = tool.schema.safeParse(input)
    if (!parsed.success) {
        return { parsed: false }
    }

    const outcome: Outcome = {
        parsed: true,
        data: JSON.parse(JSON.stringify(parsed.data)),
        ignoredKeys: findIgnoredInputKeys(input, parsed.data, tool.schema),
    }
    const { context, recorded } = fakeContext()
    try {
        await tool.handler(context, parsed.data)
    } catch (error) {
        outcome.error = error instanceof Error ? error.message : String(error)
    }
    return { ...outcome, calls: recorded.calls }
}

const MODES: Record<string, SampleOptions> = {
    'every param': { full: true },
    'required params only': { full: false },
    'numbers and booleans as strings': { full: true, asText: true },
    'datetimes with a UTC offset': { full: true, offsetDatetimes: true },
    'keys the schema does not declare': { full: true, unknownKeys: true },
}

describe('CLI catalog parity', () => {
    const catalog = buildCliCatalog(null)
    const loaded = loadCatalog(catalog)

    it('this build can run every entry the catalog serves', () => {
        expect(loaded.ok && loaded.dropped).toEqual([])
    })

    const cases = catalog.tools.flatMap((entry) => Object.keys(MODES).map((mode) => [entry.name, mode, entry] as const))

    it.each(cases)('%s parses and sends the same as the compiled tool, with %s', async (name, mode, entry) => {
        const compiled = GENERATED_TOOL_MAP[name]!()
        const fromCatalog = catalogTool(entry)
        const input = sample(entry.inputSchema, MODES[mode]!, entry.inputSchema) ?? {}

        const expected = await run(compiled, input)
        const actual = await run(fromCatalog, input)

        expect(actual).toStrictEqual(expected)
        expect(readParamAliases(fromCatalog.schema) ?? {}).toEqual(readParamAliases(compiled.schema) ?? {})
    })

    it('exercises most tools with input both schemas accept', async () => {
        let accepted = 0
        for (const entry of catalog.tools) {
            const compiled = GENERATED_TOOL_MAP[entry.name]!()
            const input = sample(entry.inputSchema, { full: true }, entry.inputSchema) ?? {}
            if (compiled.schema.safeParse(input).success) {
                accepted++
            }
        }

        expect(accepted / catalog.tools.length).toBeGreaterThan(0.9)
    })
})
