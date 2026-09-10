import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/ai_observability'
import type { Context } from '@/tools/types'

function createContext(): { context: Context; requestMock: ReturnType<typeof vi.fn> } {
    const requestMock = vi.fn().mockResolvedValue({})
    const context = {
        api: { request: requestMock },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
    } as unknown as Context
    return { context, requestMock }
}

// Production traces show these tools rejecting their failed calls at the schema, before any request
// goes out: the evaluation tools and `llma-prompt-get` because the agent named the identifier
// something the schema didn't declare, and `llma-evaluation-judge-models` because it demanded a
// single `provider` while agents were asking for the whole catalog. The inputs below are the keys
// and values those traces record, so dropping an alias map or making `provider` required again
// fails here.
describe('llma identifier contracts', () => {
    // The write tools share the mismatch, so they share the alias map. Without that, an agent that
    // succeeds with `evaluationId` on get is rejected the moment it updates or deletes.
    describe.each([['llma-evaluation-get'], ['llma-evaluation-update'], ['llma-evaluation-delete']])(
        '%s normalizes aliases to `id`',
        (toolName) => {
            const schema = GENERATED_TOOLS[toolName]!().schema
            const ALIAS_KEYS = ['evaluationId', 'evaluation_id'] as const

            it.each([
                ['id', { id: 'e1' }, 'e1'],
                ['evaluationId', { evaluationId: 'e1' }, 'e1'],
                ['evaluation_id', { evaluation_id: 'e1' }, 'e1'],
                ['id over aliases on conflict', { id: 'e1', evaluationId: 'e2' }, 'e1'],
                ['first-listed alias on alias conflict', { evaluationId: 'e1', evaluation_id: 'e2' }, 'e1'],
            ])('accepts %s', (_label, input, expected) => {
                const result = schema.safeParse(input)
                expect(result.success).toBe(true)
                const data = result.data as Record<string, unknown>
                expect(data.id).toBe(expected)
                for (const alias of ALIAS_KEYS) {
                    expect(data).not.toHaveProperty(alias)
                }
            })

            it('still rejects a call with no identifier', () => {
                expect(schema.safeParse({}).success).toBe(false)
            })
        }
    )

    describe('llma-evaluation-run normalizes aliases to `evaluation_id`', () => {
        const schema = GENERATED_TOOLS['llma-evaluation-run']!().schema
        const runInput = {
            target_event_id: '019f5632-6df1-0000-5093-46d18b1bc987',
            timestamp: '2026-01-01T00:00:00Z',
        }

        it.each([
            ['evaluation_id', { evaluation_id: 'e1' }, 'e1'],
            ['evaluationId', { evaluationId: 'e1' }, 'e1'],
            ['id', { id: 'e1' }, 'e1'],
            ['evaluation_id over aliases on conflict', { evaluation_id: 'e1', evaluationId: 'e2' }, 'e1'],
        ])('accepts %s', (_label, identifier, expected) => {
            const result = schema.safeParse({ ...runInput, ...identifier })
            expect(result.success).toBe(true)
            expect((result.data as Record<string, unknown>).evaluation_id).toBe(expected)
        })

        it('still rejects a call with no identifier', () => {
            expect(schema.safeParse(runInput).success).toBe(false)
        })
    })

    describe('llma-prompt-get normalizes aliases to `prompt_name`', () => {
        const schema = GENERATED_TOOLS['llma-prompt-get']!().schema
        const ALIAS_KEYS = ['name', 'promptName', 'prompt_id', 'promptId', 'id'] as const

        it.each([
            ['prompt_name', { prompt_name: 'greeting' }, 'greeting'],
            ['name', { name: 'greeting' }, 'greeting'],
            ['promptName', { promptName: 'greeting' }, 'greeting'],
            ['prompt_id', { prompt_id: 'greeting' }, 'greeting'],
            ['promptId', { promptId: 'greeting' }, 'greeting'],
            ['id', { id: 'greeting' }, 'greeting'],
            ['prompt_name over aliases on conflict', { prompt_name: 'greeting', name: 'other' }, 'greeting'],
            ['first-listed alias on alias conflict', { name: 'greeting', id: 'other' }, 'greeting'],
        ])('accepts %s', (_label, input, expected) => {
            const result = schema.safeParse(input)
            expect(result.success).toBe(true)
            const data = result.data as Record<string, unknown>
            expect(data.prompt_name).toBe(expected)
            for (const alias of ALIAS_KEYS) {
                expect(data).not.toHaveProperty(alias)
            }
        })

        it('keeps query params alongside a normalized alias', () => {
            const result = schema.safeParse({ name: 'greeting', label: 'production', content: 'none' })
            expect(result.success).toBe(true)
            expect(result.data).toMatchObject({ prompt_name: 'greeting', label: 'production', content: 'none' })
        })

        it('still rejects a call with no identifier', () => {
            expect(schema.safeParse({}).success).toBe(false)
        })
    })

    describe('llma-evaluation-judge-models treats `provider` as a filter', () => {
        const schema = GENERATED_TOOLS['llma-evaluation-judge-models']!().schema

        it('accepts a call with no arguments so the whole catalog is reachable', () => {
            const result = schema.safeParse({})
            expect(result.success).toBe(true)
            expect(result.data).not.toHaveProperty('provider')
        })

        it('accepts key_id on its own, since a key implies its provider', () => {
            const result = schema.safeParse({ key_id: 'k1' })
            expect(result.success).toBe(true)
            expect(result.data).toMatchObject({ key_id: 'k1' })
        })

        it.each([['openai'], ['azure_openai'], ['gemini']])('still accepts the supported provider %s', (provider) => {
            expect(schema.safeParse({ provider }).success).toBe(true)
        })

        it.each([['google'], ['OpenAI'], ['all']])('still rejects the unsupported provider %s', (provider) => {
            expect(schema.safeParse({ provider }).success).toBe(false)
        })
    })

    // Both dispatchers parse first and hand the parsed value to the handler. If either passed the
    // raw input instead, an aliased call would clear validation and then build
    // `.../name/undefined/`, so the caller would get a 404 that hides which field was wrong.
    describe.each([
        ['llma-prompt-get', { name: 'greeting' }, '/api/projects/17/llm_prompts/name/greeting/'],
        ['llma-evaluation-get', { evaluationId: 'e1' }, '/api/projects/17/evaluations/e1/'],
    ])('%s puts the aliased identifier in the request path', (toolName, input, expectedPath) => {
        it('builds the path from the normalized param', async () => {
            const { context, requestMock } = createContext()
            const tool = GENERATED_TOOLS[toolName]!()

            await tool.handler(context, tool.schema.parse(input) as never)

            expect(requestMock).toHaveBeenCalledWith(expect.objectContaining({ path: expectedPath }))
        })
    })
})
