import { describe, expect, it, vi } from 'vitest'

import { getToolByName } from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/skills'
import { SKILL_DEPRECATED_ALIASES } from '@/tools/skills/deprecatedAliases'
import type { Context } from '@/tools/types'

function createContext(requestReturnValue: unknown): { context: Context; requestMock: ReturnType<typeof vi.fn> } {
    const requestMock = vi.fn().mockResolvedValue(requestReturnValue)

    const context = {
        api: {
            request: requestMock,
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('17'),
        },
    } as unknown as Context

    return { context, requestMock }
}

describe('Generated skill-* tools', () => {
    it('uses skill_name in generated skill-archive schema', () => {
        const tool = getToolByName(GENERATED_TOOLS, 'skill-archive')

        const parsed = tool.schema.parse({ skill_name: 'skills-store' })
        expect(parsed).toEqual({ skill_name: 'skills-store' })
        expect(() => tool.schema.parse({ name: 'skills-store' })).toThrow()
    })

    it('wires skill-archive to POST /name/{skill_name}/archive/', async () => {
        const { context, requestMock } = createContext(undefined)
        const tool = getToolByName(GENERATED_TOOLS, 'skill-archive')

        const result = await tool.handler(context, { skill_name: 'skills-store' })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/17/llm_skills/name/skills-store/archive/',
        })
        expect(result).toBeUndefined()
    })

    it('deprecated llma-skill-* alias forwards to the renamed handler and annotates the response', async () => {
        const { context, requestMock } = createContext({ name: 'skills-store' })
        const alias = SKILL_DEPRECATED_ALIASES['llma-skill-get']!()

        expect(alias.name).toBe('llma-skill-get')

        const result = (await alias.handler(context, { skill_name: 'skills-store' })) as Record<string, unknown>

        expect(requestMock).toHaveBeenCalledWith(
            expect.objectContaining({
                method: 'GET',
                path: '/api/projects/17/llm_skills/name/skills-store/',
            })
        )
        expect(result.name).toBe('skills-store')
        expect(result._deprecation_notice).toContain('skill-get')
    })
})
