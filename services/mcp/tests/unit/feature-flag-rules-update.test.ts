import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getRequiredFeatureFlags, getToolDefinition, getToolsForFeatures } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

const TOOL = 'feature-flag-rules-update'
const FLAG = 'feature-flag-rules-v2-mcp'

const FILTERS = {
    version: 2,
    return_type: 'string',
    default_value: 'off',
    rules: [
        {
            id: '0b7f3c52-5a0e-4d1e-9a4c-3f1b2e6d8c90',
            rule_type: 'percentage_rollout',
            targeting: { properties: [] },
            value: 'on',
            rollout_percentage: 40,
            on_rollout_miss: 'continue',
            assignment_algorithm: 'sha1_60_v1',
            seed: 'b8e1d0a4-7c2f-4e9b-8d3a-6f5c4b3a2e10',
        },
        {
            rule_type: 'targeted_release',
            targeting: { properties: [{ key: 'plan', type: 'person', operator: 'exact', value: ['team'] }] },
            value: 'on',
        },
    ],
}

function mockContext(request: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request, getProjectBaseUrl: () => 'https://app.posthog.com/project/17' },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
    } as unknown as Context
}

describe('feature-flag-rules-update', () => {
    it('is hidden unless its flag is on', () => {
        expect(getRequiredFeatureFlags()).toContain(FLAG)
        expect(getToolsForFeatures({ featureFlags: {} })).not.toContain(TOOL)
        expect(getToolsForFeatures({ featureFlags: { [FLAG]: false } })).not.toContain(TOOL)
        expect(getToolsForFeatures({ featureFlags: { [FLAG]: true } })).toContain(TOOL)
    })

    it('leaves update-feature-flag visible either way', () => {
        expect(getToolsForFeatures({ featureFlags: {} })).toContain('update-feature-flag')
        expect(getToolsForFeatures({ featureFlags: { [FLAG]: true } })).toContain('update-feature-flag')
        expect(getToolDefinition('update-feature-flag').feature_flag).toBeUndefined()
    })

    it('is destructive and requires write scope', () => {
        const definition = getToolDefinition(TOOL)
        expect(definition.required_scopes).toEqual(['feature_flag:write'])
        expect(definition.annotations).toMatchObject({
            readOnlyHint: false,
            destructiveHint: true,
            idempotentHint: false,
        })
    })

    it('requires the flag id, the row version and a version 2 document', () => {
        const schema = z.toJSONSchema(GENERATED_TOOL_MAP[TOOL]!().schema, { io: 'input', reused: 'inline' }) as {
            required?: string[]
        }
        expect(schema.required?.sort()).toEqual(['filters', 'id', 'version'])

        const tool = GENERATED_TOOL_MAP[TOOL]!()
        expect(tool.schema.safeParse({ id: 42, version: 3, filters: FILTERS }).success).toBe(true)
        expect(tool.schema.safeParse({ id: 42, filters: FILTERS }).success).toBe(false)
        expect(tool.schema.safeParse({ id: 42, version: 3, filters: { ...FILTERS, version: 1 } }).success).toBe(false)
    })

    it('sends the whole document and the row version in one PATCH', async () => {
        const request = vi.fn().mockResolvedValue({ id: 42, key: 'checkout', version: 4, filters: FILTERS })
        const filters = { ...FILTERS, aggregation_group_type_index: 0 }

        const result = await GENERATED_TOOL_MAP[TOOL]!().handler(mockContext(request), { id: 42, version: 3, filters })

        expect(result).toMatchObject({
            id: 42,
            key: 'checkout',
            version: 4,
            filters: FILTERS,
            _posthogUrl: 'https://app.posthog.com/project/17/feature-flags/42',
        })
        expect(request).toHaveBeenCalledExactlyOnceWith({
            method: 'PATCH',
            path: '/api/projects/17/feature_flags/42/',
            body: { version: 3, filters },
        })
    })

    it('surfaces a refused write instead of swallowing it', async () => {
        const refused = new Error('Conflict: the flag changed after version 3')
        const request = vi.fn().mockRejectedValue(refused)

        await expect(
            GENERATED_TOOL_MAP[TOOL]!().handler(mockContext(request), { id: 42, version: 3, filters: FILTERS })
        ).rejects.toBe(refused)
    })
})
