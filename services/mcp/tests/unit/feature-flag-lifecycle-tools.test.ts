import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

const LIFECYCLE_TOOLS = [
    'feature-flag-enable',
    'feature-flag-disable',
    'feature-flag-archive',
    'feature-flag-unarchive',
]

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

describe('feature flag lifecycle tools', () => {
    // The snapshot test would also catch a `filters` param appearing here, but it is
    // silenced by `vitest -u`. These assertions are not: the whole point of the lifecycle
    // tools is that an agent cannot send targeting through them.
    it.each(LIFECYCLE_TOOLS)('%s takes the flag id and nothing else', (name) => {
        const tool = GENERATED_TOOL_MAP[name]?.()
        expect(tool, `${name} is missing from the generated tool map`).not.toBeUndefined()

        const schema = z.toJSONSchema(tool!.schema, { io: 'input', reused: 'inline' }) as {
            properties?: Record<string, unknown>
            required?: string[]
        }

        expect(Object.keys(schema.properties ?? {})).toEqual(['id'])
        expect(schema.required).toEqual(['id'])
    })

    it.each(LIFECYCLE_TOOLS)('%s declares the write scope and a reversible, idempotent action', (name) => {
        const definition = getToolDefinition(name)

        expect(definition.description).toContain('never accepts or replaces the `filters` object')
        expect(definition.required_scopes).toEqual(['feature_flag:write'])
        expect(definition.annotations?.readOnlyHint).toBe(false)
        expect(definition.annotations?.destructiveHint).toBe(false)
        expect(definition.annotations?.idempotentHint).toBe(true)
    })

    // The tool name and the URL it posts to come from separate lines of the same YAML entry,
    // so nothing above notices `feature-flag-enable` wired to `/disable/`. An agent asked to
    // turn a flag on would turn it off.
    it.each(LIFECYCLE_TOOLS)('%s posts to its own endpoint', async (name) => {
        const requestMock = vi.fn().mockResolvedValue({ id: 42 })
        const context = {
            api: {
                request: requestMock,
                getProjectBaseUrl: () => 'https://app.posthog.com/project/17',
            },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
        } as unknown as Context

        await GENERATED_TOOL_MAP[name]!().handler(context, { id: 42 })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'POST',
            path: `/api/projects/17/feature_flags/42/${name.replace('feature-flag-', '')}/`,
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
            const context = {
                api: {
                    request: requestMock,
                    getProjectBaseUrl: () => 'https://app.posthog.com/project/17',
                },
                stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
            } as unknown as Context

            await GENERATED_TOOL_MAP[name]!().handler(context, input)

            expect(requestMock).toHaveBeenCalledExactlyOnceWith({ method: 'POST', path, body })
        }
    )
})
