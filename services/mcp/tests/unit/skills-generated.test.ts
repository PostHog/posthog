import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { getToolByName } from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/llm_analytics'
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

describe('Generated llma-skill-* tools', () => {
    it('uses skill_name in generated skill-archive schema', () => {
        const tool = getToolByName(GENERATED_TOOLS, 'llma-skill-archive')

        const parsed = tool.schema.parse({ skill_name: 'skills-store' })
        expect(parsed).toEqual({ skill_name: 'skills-store' })
        expect(() => tool.schema.parse({ name: 'skills-store' })).toThrow()
    })

    it('wires skill-archive to POST /name/{skill_name}/archive/', async () => {
        const { context, requestMock } = createContext(undefined)
        const tool = getToolByName(GENERATED_TOOLS, 'llma-skill-archive')

        const result = await tool.handler(context, { skill_name: 'skills-store' })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/environments/17/llm_skills/name/skills-store/archive/',
        })
        expect(result).toBeUndefined()
    })

    // Regression test for issue #60049 — guards against codegen drift in the
    // four name-keyed skill endpoints. The MCP tool input schema is generated
    // from the Django URL kwarg name; renaming the kwarg silently renames the
    // public required parameter. Each of these tools must take `skill_name`.
    it.each([
        ['llma-skill-archive'],
        ['llma-skill-get'],
        ['llma-skill-update'],
        ['llma-skill-duplicate'],
        ['llma-skill-file-create'],
        ['llma-skill-file-delete'],
        ['llma-skill-file-get'],
        ['llma-skill-file-rename'],
    ])('exposes skill_name (not skill_identifier) in %s schema', (toolName) => {
        const tool = getToolByName(GENERATED_TOOLS, toolName)
        const shape = (tool.schema as unknown as z.ZodObject<z.ZodRawShape>).shape
        expect(shape).toHaveProperty('skill_name')
        expect(shape).not.toHaveProperty('skill_identifier')
    })

    it('wires skill-get to GET /name/{skill_name}/', async () => {
        const { context, requestMock } = createContext({ id: '1', name: 'skills-store' })
        const tool = getToolByName(GENERATED_TOOLS, 'llma-skill-get')

        await tool.handler(context, { skill_name: 'skills-store' })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/environments/17/llm_skills/name/skills-store/',
            query: { version: undefined },
        })
    })

    it('wires skill-update to PATCH /name/{skill_name}/', async () => {
        const { context, requestMock } = createContext({ id: '1', name: 'skills-store' })
        const tool = getToolByName(GENERATED_TOOLS, 'llma-skill-update')

        await tool.handler(context, { skill_name: 'skills-store', base_version: 1, body: '# Updated' })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'PATCH',
            path: '/api/environments/17/llm_skills/name/skills-store/',
            body: { body: '# Updated', base_version: 1 },
        })
    })
})
