import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { hasScopes } from '@/lib/api'
import { getToolsFromContext } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

describe('message category setup tools', () => {
    it.each([false, true, undefined])('category setup exposure requires the agent rollout: %s', async (enabled) => {
        const context = {
            stateManager: {
                getApiKey: async () => ({ scopes: ['hog_flow:write'] }),
                getAiConsentGiven: async () => true,
            },
        } as unknown as Context
        const tools = await getToolsFromContext(context, {
            featureFlags: { 'workflows-email-domain-agent-setup': enabled },
        })
        const names = tools.map((tool) => tool.name)
        expect(names.filter((name) => name.startsWith('messaging-categories-')).sort()).toEqual(
            enabled === true
                ? [
                      'messaging-categories-create',
                      'messaging-categories-list',
                      'messaging-categories-partial-update',
                      'messaging-categories-retrieve',
                  ]
                : []
        )
        expect(names).toContain('workflows-get')
    })
    it('exposes only category setup actions', () => {
        expect(
            Object.keys(GENERATED_TOOL_MAP)
                .filter((name) => name.startsWith('messaging-categories-'))
                .sort()
        ).toEqual([
            'messaging-categories-create',
            'messaging-categories-list',
            'messaging-categories-partial-update',
            'messaging-categories-retrieve',
        ])
    })
    it.each(['messaging-categories-list', 'messaging-categories-retrieve'])(
        '%s is available to a workflow read credential',
        (name) => {
            expect(GENERATED_TOOL_MAP[name]).not.toBeUndefined()
            const scopes = getToolDefinition(name).required_scopes ?? []
            expect(hasScopes(['hog_flow:read'], scopes)).toBe(true)
            expect(hasScopes(['insight:read'], scopes)).toBe(false)
        }
    )

    it.each(['messaging-categories-create', 'messaging-categories-partial-update'])(
        '%s requires workflow write access and excludes deletion',
        (name) => {
            const tool = GENERATED_TOOL_MAP[name]?.()
            expect(tool).not.toBeUndefined()
            const scopes = getToolDefinition(name).required_scopes ?? []
            expect(hasScopes(['hog_flow:write'], scopes)).toBe(true)
            expect(hasScopes(['hog_flow:read'], scopes)).toBe(false)
            const schema = z.toJSONSchema(tool!.schema) as { properties: Record<string, unknown> }
            expect(schema.properties).not.toHaveProperty('deleted')
            if (name === 'messaging-categories-partial-update') {
                expect(schema.properties).not.toHaveProperty('key')
            }
        }
    )

    it.each([
        {
            name: 'messaging-categories-create',
            input: { key: 'updates', name: 'Updates', category_type: 'marketing' },
            method: 'POST',
            path: '/api/projects/17/messaging_categories/',
            body: { key: 'updates', name: 'Updates', category_type: 'marketing' },
        },
        {
            name: 'messaging-categories-partial-update',
            input: { id: '00000000-0000-4000-8000-000000000001', name: 'Product updates' },
            method: 'PATCH',
            path: '/api/projects/17/messaging_categories/00000000-0000-4000-8000-000000000001/',
            body: { name: 'Product updates' },
        },
    ])(
        '$name sends only the supplied category fields to the project endpoint',
        async ({ name, input, method, path, body }) => {
            const request = vi.fn().mockResolvedValue({ ...body, id: '00000000-0000-4000-8000-000000000001' })
            const context = {
                api: { request },
                stateManager: { getProjectId: async () => '17' },
            } as unknown as Context
            const tool = GENERATED_TOOL_MAP[name]!()
            await tool.handler(context, tool.schema.parse(input))
            expect(request).toHaveBeenCalledExactlyOnceWith({ method, path, body })
        }
    )
})
