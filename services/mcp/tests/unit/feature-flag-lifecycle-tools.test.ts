import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

// The toggles also take `version`: a flag on config version 2 refuses a toggle without it.
const LIFECYCLE_TOOLS = [
    {
        name: 'feature-flag-enable',
        case: 'versioned',
        keys: ['id', 'version'],
        input: { id: 42, version: 3 },
        body: { version: 3 },
    },
    {
        name: 'feature-flag-disable',
        case: 'versioned',
        keys: ['id', 'version'],
        input: { id: 42, version: 3 },
        body: { version: 3 },
    },
    { name: 'feature-flag-enable', case: 'unversioned', keys: ['id', 'version'], input: { id: 42 }, body: {} },
    { name: 'feature-flag-archive', case: 'no body', keys: ['id'], input: { id: 42 }, body: undefined },
    { name: 'feature-flag-unarchive', case: 'no body', keys: ['id'], input: { id: 42 }, body: undefined },
] as const

const ROLLOUT_TOOLS = [
    {
        name: 'feature-flag-roll-out-to-everyone',
        keys: ['id', 'variant_key', 'version'],
        required: ['id', 'version'],
        input: { id: 42, version: 3, variant_key: 'control' },
        path: '/api/projects/17/feature_flags/42/roll_out_to_everyone/',
        body: { version: 3, variant_key: 'control' },
    },
    {
        name: 'feature-flag-set-release-condition-rollout',
        keys: ['condition_index', 'id', 'rollout_percentage', 'version'],
        required: ['id', 'condition_index', 'rollout_percentage', 'version'],
        input: { id: 42, condition_index: 1, rollout_percentage: 25, version: 3 },
        path: '/api/projects/17/feature_flags/42/set_release_condition_rollout/',
        body: { condition_index: 1, rollout_percentage: 25, version: 3 },
    },
] as const

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: () => 'https://app.posthog.com/project/17',
        },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
    } as unknown as Context
}

describe('feature flag lifecycle tools', () => {
    // The snapshot test would also catch a `filters` param appearing here, but it is
    // silenced by `vitest -u`. These assertions are not: the whole point of the lifecycle
    // tools is that an agent cannot send targeting through them.
    it.each(LIFECYCLE_TOOLS)('$name takes the flag id and no targeting ($case)', ({ name, keys }) => {
        const tool = GENERATED_TOOL_MAP[name]?.()
        expect(tool, `${name} is missing from the generated tool map`).not.toBeUndefined()

        const schema = z.toJSONSchema(tool!.schema, { io: 'input', reused: 'inline' }) as {
            properties?: Record<string, unknown>
            required?: string[]
        }

        expect(Object.keys(schema.properties ?? {}).sort()).toEqual([...keys].sort())
        expect(schema.required).toEqual(['id'])
    })

    it.each(LIFECYCLE_TOOLS)(
        '$name declares the write scope and a reversible, idempotent action ($case)',
        ({ name }) => {
            const definition = getToolDefinition(name)

            expect(definition.description).toContain('never accepts or replaces the `filters` object')
            expect(definition.required_scopes).toEqual(['feature_flag:write'])
            expect(definition.annotations?.readOnlyHint).toBe(false)
            expect(definition.annotations?.destructiveHint).toBe(false)
            expect(definition.annotations?.idempotentHint).toBe(true)
        }
    )

    // The tool name and the URL it posts to come from separate lines of the same YAML entry,
    // so nothing above notices `feature-flag-enable` wired to `/disable/`. An agent asked to
    // turn a flag on would turn it off.
    it.each(LIFECYCLE_TOOLS)('$name posts to its own endpoint ($case)', async ({ name, input, body }) => {
        const requestMock = vi.fn().mockResolvedValue({ id: 42 })
        const context = createMockContext(requestMock)

        await GENERATED_TOOL_MAP[name]!().handler(context, input)

        expect(requestMock).toHaveBeenCalledExactlyOnceWith({
            method: 'POST',
            path: `/api/projects/17/feature_flags/42/${name.replace('feature-flag-', '')}/`,
            ...(body === undefined ? {} : { body }),
        })
    })
    it.each(ROLLOUT_TOOLS)('$name exposes only the intended fields and annotations', ({ name, keys, required }) => {
        const tool = GENERATED_TOOL_MAP[name]?.()
        expect(tool, `${name} is missing from the generated tool map`).not.toBeUndefined()

        const schema = z.toJSONSchema(tool!.schema, { io: 'input', reused: 'inline' }) as {
            properties?: Record<string, unknown>
            required?: string[]
        }

        expect(Object.keys(schema.properties ?? {}).sort()).toEqual([...keys].sort())
        expect(schema.required?.sort()).toEqual([...required].sort())

        const definition = getToolDefinition(name)
        expect(definition.required_scopes).toEqual(['feature_flag:write'])
        expect(definition.annotations?.readOnlyHint).toBe(false)
        expect(definition.annotations?.destructiveHint).toBe(false)
        expect(definition.annotations?.idempotentHint).toBe(false)
    })

    it.each(ROLLOUT_TOOLS)(
        '$name posts the version and rollout fields to its endpoint',
        async ({ name, input, path, body }) => {
            const requestMock = vi.fn().mockResolvedValue({ id: 42 })
            const context = createMockContext(requestMock)

            await GENERATED_TOOL_MAP[name]!().handler(context, input)

            expect(requestMock).toHaveBeenCalledExactlyOnceWith({ method: 'POST', path, body })
        }
    )
})

// A flag on config version 2 refuses any PATCH without the row `version`, a soft delete included.
const VERSIONED_PATCH_TOOLS = [
    {
        name: 'delete-feature-flag',
        case: 'versioned',
        input: { id: 42, version: 3 },
        body: { version: 3, deleted: true },
    },
    { name: 'delete-feature-flag', case: 'unversioned', input: { id: 42 }, body: { deleted: true } },
    {
        name: 'update-feature-flag',
        case: 'versioned',
        input: { id: 42, name: 'Renamed', version: 3 },
        body: { name: 'Renamed', version: 3 },
    },
    { name: 'update-feature-flag', case: 'unversioned', input: { id: 42, name: 'Renamed' }, body: { name: 'Renamed' } },
] as const

describe('feature flag PATCH tools', () => {
    it.each(['delete-feature-flag', 'update-feature-flag'])('%s takes an optional version', (name) => {
        const schema = z.toJSONSchema(GENERATED_TOOL_MAP[name]!().schema, { io: 'input', reused: 'inline' }) as {
            properties?: Record<string, unknown>
            required?: string[]
        }

        expect(schema.properties).toHaveProperty('version')
        expect(schema.required).toEqual(['id'])
    })

    it('delete-feature-flag takes only the flag id and version', () => {
        const schema = z.toJSONSchema(GENERATED_TOOL_MAP['delete-feature-flag']!().schema, {
            io: 'input',
            reused: 'inline',
        }) as { properties?: Record<string, unknown> }

        expect(Object.keys(schema.properties ?? {}).sort()).toEqual(['id', 'version'])
    })

    it.each(VERSIONED_PATCH_TOOLS)('$name sends version only when given ($case)', async ({ name, input, body }) => {
        const requestMock = vi.fn().mockResolvedValue({ id: 42 })
        const context = createMockContext(requestMock)

        await GENERATED_TOOL_MAP[name]!().handler(context, input)

        expect(requestMock).toHaveBeenCalledExactlyOnceWith({
            method: 'PATCH',
            path: '/api/projects/17/feature_flags/42/',
            body,
        })
    })

    it('delete-feature-flag always soft-deletes, whatever else the caller sends', async () => {
        const requestMock = vi.fn().mockResolvedValue({ id: 42 })
        const context = createMockContext(requestMock)
        const tool = GENERATED_TOOL_MAP['delete-feature-flag']!()

        await tool.handler(context, tool.schema.parse({ id: 42, version: 3, deleted: false, name: 'Renamed' }))

        expect(requestMock).toHaveBeenCalledExactlyOnceWith({
            method: 'PATCH',
            path: '/api/projects/17/feature_flags/42/',
            body: { version: 3, deleted: true },
        })
    })
})
