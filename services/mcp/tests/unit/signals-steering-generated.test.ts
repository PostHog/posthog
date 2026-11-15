import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/signals'
import type { Context } from '@/tools/types'

describe('Self-driving steering tools', () => {
    it('passes atomic source config key edits through without stripping source-specific keys', async () => {
        const request = vi.fn().mockResolvedValue({ id: 'source-example', config: {} })
        const context = {
            api: { request },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const tool = GENERATED_TOOLS['inbox-source-configs-partial-update']!()
        const input = {
            id: 'source-example',
            config_set: { steering: 'Prioritize documentation tasks', hogql_filter: 'false', nested: { keep: true } },
            config_remove: ['default_not_actionable'],
        }
        await tool.handler(context, tool.schema.parse(input))
        expect(request).toHaveBeenCalledWith({
            method: 'PATCH',
            path: '/api/projects/42/signals/source_configs/source-example/',
            body: { config_set: input.config_set, config_remove: input.config_remove },
        })
    })

    it.each(['inbox-steering-instructions-get', 'inbox-steering-instructions-update'])(
        '%s uses the current project and returns only steering fields',
        async (name) => {
            const instructions = {
                research_instructions: '',
                implementation_instructions: 'Run regression tests.',
                scout_instructions: 'Inspect onboarding.',
            }
            const request = vi.fn().mockResolvedValue({ ...instructions, autostart_enabled: false })
            const context = {
                api: { request },
                stateManager: { getProjectId: async () => '42' },
            } as unknown as Context
            const tool = GENERATED_TOOLS[name]!()
            const input =
                name === 'inbox-steering-instructions-update'
                    ? { research_instructions: '', autostart_enabled: true }
                    : {}

            expect(await tool.handler(context, tool.schema.parse(input))).toEqual(instructions)
            expect(request).toHaveBeenCalledWith({
                method: name === 'inbox-steering-instructions-get' ? 'GET' : 'POST',
                path: '/api/projects/42/signals/config/',
                ...(name === 'inbox-steering-instructions-update' ? { body: { research_instructions: '' } } : {}),
            })
        }
    )

    it.each(['research_instructions', 'implementation_instructions', 'scout_instructions'])(
        'enforces the API length and null constraints for %s',
        (field) => {
            const schema = GENERATED_TOOLS['inbox-steering-instructions-update']!().schema
            expect(schema.safeParse({ [field]: null }).success).toBe(false)
            expect(schema.safeParse({ [field]: 'x'.repeat(20_001) }).success).toBe(false)
            expect(schema.parse({ [field]: 'x'.repeat(20_000) })).toEqual({ [field]: 'x'.repeat(20_000) })
        }
    )
})
