import { describe, expect, it, vi } from 'vitest'

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

describe('Generated llma-prompt-* tools', () => {
    it('uses prompt_name (not name) in generated prompt-get schema', () => {
        const tool = getToolByName(GENERATED_TOOLS, 'llma-prompt-get')

        const parsed = tool.schema.parse({ prompt_name: 'checkout_prompt', version: 2 })
        expect(parsed).toEqual({ prompt_name: 'checkout_prompt', version: 2, content: 'full' })
        expect(() => tool.schema.parse({ name: 'checkout_prompt' })).toThrow()
    })

    it('exposes content mode on the prompt-get schema so agents can fetch outline-only', () => {
        const tool = getToolByName(GENERATED_TOOLS, 'llma-prompt-get')

        const parsed = tool.schema.parse({ prompt_name: 'checkout_prompt', content: 'none' })
        expect(parsed).toEqual({ prompt_name: 'checkout_prompt', content: 'none' })
        expect(() => tool.schema.parse({ prompt_name: 'checkout_prompt', content: 'bogus' })).toThrow()
    })

    it('uses prompt_name (not name) in generated prompt-update schema', () => {
        const tool = getToolByName(GENERATED_TOOLS, 'llma-prompt-update')

        const parsed = tool.schema.parse({ prompt_name: 'checkout_prompt', prompt: { text: 'v2' }, base_version: 1 })
        expect(parsed).toEqual({ prompt_name: 'checkout_prompt', prompt: { text: 'v2' }, base_version: 1 })
        expect(() => tool.schema.parse({ name: 'checkout_prompt', prompt: { text: 'v2' } })).toThrow()
    })

    it('wires prompt-list to GET and preserves paginated output shape', async () => {
        const paginated = {
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    id: '2f53a52a-06f5-4025-9ea7-f763f74f17f5',
                    name: 'checkout_prompt',
                    version: 3,
                    prompt_size_bytes: 123,
                },
            ],
        }
        const { context, requestMock } = createContext(paginated)
        const tool = getToolByName(GENERATED_TOOLS, 'llma-prompt-list')

        const result = await tool.handler(context, { search: 'checkout' })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/environments/17/llm_prompts/',
            query: { search: 'checkout', content: 'none' },
        })
        expect(result).toEqual(paginated)
    })

    it('allows overriding prompt-list content mode', async () => {
        const { context, requestMock } = createContext({ count: 0, next: null, previous: null, results: [] })
        const tool = getToolByName(GENERATED_TOOLS, 'llma-prompt-list')

        await tool.handler(context, { search: 'checkout', content: 'preview' })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/environments/17/llm_prompts/',
            query: { search: 'checkout', content: 'preview' },
        })
    })

    it('wires prompt-get to GET /name/{prompt_name}/ with version query', async () => {
        const response = { id: '2f53a52a-06f5-4025-9ea7-f763f74f17f5', name: 'checkout_prompt', version: 2 }
        const { context, requestMock } = createContext(response)
        const tool = getToolByName(GENERATED_TOOLS, 'llma-prompt-get')

        await tool.handler(context, { prompt_name: 'checkout_prompt', version: 2 })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/environments/17/llm_prompts/name/checkout_prompt/',
            query: { version: 2 },
        })
    })

    it('wires prompt-create to POST body with name and prompt', async () => {
        const { context, requestMock } = createContext({ id: 'new-id' })
        const tool = getToolByName(GENERATED_TOOLS, 'llma-prompt-create')

        await tool.handler(context, { name: 'new_prompt', prompt: { text: 'hello' } })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/environments/17/llm_prompts/',
            body: { name: 'new_prompt', prompt: { text: 'hello' } },
        })
    })

    it('wires prompt-update to PATCH /name/{prompt_name}/ with publish payload', async () => {
        const { context, requestMock } = createContext({ id: 'updated-id' })
        const tool = getToolByName(GENERATED_TOOLS, 'llma-prompt-update')

        await tool.handler(context, { prompt_name: 'new_prompt', prompt: { text: 'v2' }, base_version: 1 })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'PATCH',
            path: '/api/environments/17/llm_prompts/name/new_prompt/',
            body: { prompt: { text: 'v2' }, base_version: 1 },
        })
    })

    it('uses prompt_name and new_name in generated prompt-duplicate schema', () => {
        const tool = getToolByName(GENERATED_TOOLS, 'llma-prompt-duplicate')

        const parsed = tool.schema.parse({ prompt_name: 'original_prompt', new_name: 'copy_of_prompt' })
        expect(parsed).toEqual({ prompt_name: 'original_prompt', new_name: 'copy_of_prompt' })
        expect(() => tool.schema.parse({ prompt_name: 'original_prompt' })).toThrow()
    })

    it('wires prompt-duplicate to POST /name/{prompt_name}/duplicate/ with new_name body', async () => {
        const response = { id: 'new-id', name: 'copy_of_prompt', version: 1 }
        const { context, requestMock } = createContext(response)
        const tool = getToolByName(GENERATED_TOOLS, 'llma-prompt-duplicate')

        const result = await tool.handler(context, { prompt_name: 'original_prompt', new_name: 'copy_of_prompt' })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/environments/17/llm_prompts/name/original_prompt/duplicate/',
            body: { new_name: 'copy_of_prompt' },
        })
        expect(result).toEqual(response)
    })
})
