import { describe, expect, it, vi } from 'vitest'

import type { Schemas } from '@/api/generated'
import { PostHogApiError } from '@/lib/errors'
import parserRecipeCreate from '@/tools/aiObservability/parserRecipeCreate'
import type { Context } from '@/tools/types'

const SOURCE =
    'rules:\n    - on:\n          acme_kind: q\n      emit:\n          role: user\n          content: $.acme_text\n'
const PARSER_TEST_PATH = '/api/projects/42/ai_observability/traces/dHJhY2UtMQ/nodes/ZXZlbnQtMQ/parser_test/'
const RECIPES_PATH = '/api/projects/42/llm_analytics/parser_recipes/'

type Side = Schemas.TraceParserTestSide

const FIXED: Side = { neededFixing: true, fixed: true, broken: false, error: null }
const UNFIXED: Side = { neededFixing: true, fixed: false, broken: false, error: null }
const FINE: Side = { neededFixing: false, fixed: false, broken: false, error: null }

function verdict(input: Side, output: Side, passed: boolean): Record<string, unknown> {
    return {
        content: { input: { kind: 'json', value: null }, output: { kind: 'json', value: null } },
        input,
        output,
        passed,
    }
}

function apiError(status: number, body: string): PostHogApiError {
    return new PostHogApiError({ status, statusText: '', body, url: '', method: 'POST', retryAfterSeconds: null })
}

function createContext(request: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request } as any,
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('42'),
            getApiKey: vi.fn().mockResolvedValue({}),
        } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'distinct-id',
        trackEvent: async () => {},
    } as Context
}

describe('llma-parser-recipe-create handler', () => {
    const params = { name: 'Acme SDK', yaml_source: SOURCE, trace_id: 'trace-1', event_uuid: 'event-1' }

    it('tests the parser against the event, then saves it on a pass and returns its id', async () => {
        const request = vi
            .fn()
            .mockResolvedValueOnce(verdict(FIXED, FINE, true))
            .mockResolvedValueOnce({ id: 'recipe-123' })

        const result = await parserRecipeCreate().handler(createContext(request), params)

        expect(result).toEqual({ valid: true, recipe_id: 'recipe-123' })
        expect(request.mock.calls.map(([call]) => [call.method, call.path, call.body])).toEqual([
            ['POST', PARSER_TEST_PATH, { source: SOURCE }],
            ['POST', RECIPES_PATH, { name: 'Acme SDK', source: SOURCE }],
        ])
    })

    it('sends ids that are unsafe in a path as unpadded base64url', async () => {
        const request = vi.fn().mockResolvedValueOnce(verdict(FINE, FINE, false))

        await parserRecipeCreate().handler(createContext(request), { ...params, trace_id: 'a/b-ü', event_uuid: 'x?' })

        expect(request.mock.calls[0]![0].path).toBe(
            `/api/projects/42/ai_observability/traces/${Buffer.from('a/b-ü').toString('base64url')}/nodes/eD8/parser_test/`
        )
    })

    it('saves nothing when no side needed fixing', async () => {
        const request = vi.fn().mockResolvedValueOnce(verdict(FINE, FINE, false))

        const result = await parserRecipeCreate().handler(createContext(request), params)

        expect(result).toEqual({ valid: true, already_recognized: true })
        expect(request).toHaveBeenCalledTimes(1)
    })

    it.each([
        {
            name: 'a side the parser leaves unparsed',
            input: FIXED,
            output: UNFIXED,
            expected: 'the parser does not make the output parsed',
        },
        {
            name: 'a parser that fails while running',
            input: { ...UNFIXED, error: { source: 'candidate' as const, message: 'ran out of time' } },
            output: FINE,
            expected: 'the input: ran out of time',
        },
        {
            name: 'a parser that breaks a side that was parsed',
            input: FIXED,
            output: { ...FINE, broken: true },
            expected: 'the output is parsed without your recipe but not with it',
        },
        {
            name: 'saved parsers that fail on the event',
            input: { ...UNFIXED, error: { source: 'existing_recipes' as const, message: 'ran out of time' } },
            output: FINE,
            expected: 'not a problem with your recipe',
        },
    ])('reports $name without saving', async ({ input, output, expected }) => {
        const request = vi.fn().mockResolvedValueOnce(verdict(input, output, false))

        const result = await parserRecipeCreate().handler(createContext(request), params)

        expect(result.valid).toBe(false)
        expect(result.error).toContain(expected)
        expect(request).toHaveBeenCalledTimes(1)
    })

    it.each([
        {
            status: 400,
            body: '{"detail": "Recipe YAML does not parse"}',
            expected: 'the recipe does not compile: Recipe YAML does not parse',
        },
        { status: 404, body: '{"detail": "Node not found."}', expected: 'past AI events retention' },
    ])('turns a $status from the test into a verdict', async ({ status, body, expected }) => {
        const request = vi.fn().mockRejectedValueOnce(apiError(status, body))

        const result = await parserRecipeCreate().handler(createContext(request), params)

        expect(result.valid).toBe(false)
        expect(result.error).toContain(expected)
    })

    it('throws when the test fails for another reason', async () => {
        const request = vi.fn().mockRejectedValueOnce(apiError(500, 'boom'))

        await expect(parserRecipeCreate().handler(createContext(request), params)).rejects.toThrow()
    })

    it('keeps a parser that passed when only the save fails', async () => {
        const request = vi
            .fn()
            .mockResolvedValueOnce(verdict(FIXED, FINE, true))
            .mockRejectedValueOnce(new Error('500 from API'))

        const result = await parserRecipeCreate().handler(createContext(request), params)

        expect(result).toEqual({ valid: true, saved: false, error: '500 from API' })
    })
})
