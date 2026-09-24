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

    // The file manifest from `skill-get` names a bundled file's path `path`, but the two tools that
    // address a file by URL take `file_path`. Production traces show agents carrying the manifest key
    // over and being rejected at the schema, so both tools accept `path` and normalize it.
    describe.each([['skill-file-get'], ['skill-file-delete']])('%s accepts `path` for file_path', (toolName) => {
        const schema = getToolByName(GENERATED_TOOLS, toolName).schema

        it('normalizes path to file_path', () => {
            const parsed = schema.parse({ skill_name: 'skills-store', path: 'references/limits.md' }) as Record<
                string,
                unknown
            >

            expect(parsed.file_path).toBe('references/limits.md')
            expect(parsed).not.toHaveProperty('path')
        })

        it('keeps file_path when the caller sends both keys', () => {
            const parsed = schema.parse({
                skill_name: 'skills-store',
                file_path: 'references/limits.md',
                path: 'other.md',
            }) as Record<string, unknown>

            expect(parsed.file_path).toBe('references/limits.md')
        })
    })

    it('sends the aliased path in the skill-file-get URL', async () => {
        const { context, requestMock } = createContext({ path: 'references/limits.md' })
        const tool = getToolByName(GENERATED_TOOLS, 'skill-file-get')

        await tool.handler(context, tool.schema.parse({ skill_name: 'skills-store', path: 'references/limits.md' }))

        expect(requestMock).toHaveBeenCalledWith(
            expect.objectContaining({
                method: 'GET',
                path: '/api/projects/17/llm_skills/name/skills-store/files/references%2Flimits.md/',
            })
        )
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
