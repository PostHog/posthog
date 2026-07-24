import { describe, expect, it, vi } from 'vitest'

import parserRecipeCreate from '@/tools/aiObservability/parserRecipeCreate'
import type { Context } from '@/tools/types'

// A recipe whose rule matches the `acme_*` sample shape below. The built-in recipes
// do not recognize that shape, so this recipe is what makes the sample recognized.
const MATCHING_RECIPE = `
rules:
    - on:
          acme_kind: q
      emit:
          role: user
          content: $.acme_text
`

// Compiles, but matches nothing in the sample — the event stays unrecognized.
const NON_MATCHING_RECIPE = `
rules:
    - on:
          some_other_key: { exists: true }
      emit:
          role: user
          content: $.acme_text
`

const TRACE_ID = 'trace-1'
const EVENT_UUID = 'event-1'

interface EventShape {
    id: string
    event: string
    properties: Record<string, unknown>
}

function generationEvent(overrides: Partial<EventShape> = {}): EventShape {
    return {
        id: EVENT_UUID,
        event: '$ai_generation',
        properties: {
            $ai_input: { acme_kind: 'q', acme_text: 'hi' },
            $ai_output: { acme_kind: 'q', acme_text: 'bye' },
        },
        ...overrides,
    }
}

function createContext(options: { events: EventShape[]; queryError?: string; request?: ReturnType<typeof vi.fn> }): {
    context: Context
    execute: ReturnType<typeof vi.fn>
    request: ReturnType<typeof vi.fn>
} {
    const execute = vi
        .fn()
        .mockResolvedValue(
            options.queryError
                ? { success: false, error: { message: options.queryError } }
                : { success: true, data: { results: [{ events: options.events }] } }
        )
    const request = options.request ?? vi.fn().mockResolvedValue({ results: [] })
    const context = {
        api: { request, query: vi.fn().mockReturnValue({ execute }) } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'distinct-id',
        trackEvent: async () => {},
    } as Context
    return { context, execute, request }
}

describe('llma-parser-recipe-create handler', () => {
    const baseParams = {
        name: 'Acme SDK',
        yaml_source: MATCHING_RECIPE,
        trace_id: TRACE_ID,
        event_uuid: EVENT_UUID,
    }

    it('validates against the event and persists the recipe, returning its id', async () => {
        const request = vi
            .fn()
            .mockResolvedValueOnce({ results: [] }) // GET recipes list
            .mockResolvedValueOnce({ id: 'recipe-123' }) // POST create
        const { context } = createContext({ events: [generationEvent()], request })

        const result = await parserRecipeCreate().handler(context, baseParams)

        expect(result).toEqual({ valid: true, recipe_id: 'recipe-123' })
        expect(request).toHaveBeenCalledTimes(2)
        expect(request.mock.calls[1]![0]).toMatchObject({
            method: 'POST',
            path: '/api/projects/42/llm_analytics/parser_recipes/',
            body: { name: 'Acme SDK', source: MATCHING_RECIPE },
        })
    })

    it('returns a validation error and does not persist when the source is not valid YAML', async () => {
        const { context, request } = createContext({ events: [generationEvent()] })

        const result = await parserRecipeCreate().handler(context, { ...baseParams, yaml_source: 'rules: [unclosed' })

        expect(result.valid).toBe(false)
        // Only the recipe list GET ran — nothing was POSTed.
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('rejects a recipe that compiles but leaves the event unrecognized', async () => {
        const { context, request } = createContext({ events: [generationEvent()] })

        const result = await parserRecipeCreate().handler(context, { ...baseParams, yaml_source: NON_MATCHING_RECIPE })

        expect(result.valid).toBe(false)
        expect(result.error).toContain('no rule matched')
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('reuses an identical existing recipe instead of POSTing a duplicate', async () => {
        const request = vi.fn().mockResolvedValueOnce({ results: [{ id: 'recipe-0', source: MATCHING_RECIPE }] })
        const { context } = createContext({ events: [generationEvent()], request })

        const result = await parserRecipeCreate().handler(context, baseParams)

        // The identical recipe is already installed, so the event is already recognized
        // by the time we recompute — hence the flag alongside the deduped id.
        expect(result).toEqual({ valid: true, recipe_id: 'recipe-0', already_recognized: true })
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('does not persist an unproven recipe when both sides are already recognized', async () => {
        // MATCHING_RECIPE is already installed, so validation of the candidate is vacuous —
        // a non-matching candidate must be flagged, not saved team-wide.
        const request = vi.fn().mockResolvedValueOnce({ results: [{ id: 'recipe-0', source: MATCHING_RECIPE }] })
        const { context } = createContext({ events: [generationEvent()], request })

        const result = await parserRecipeCreate().handler(context, { ...baseParams, yaml_source: NON_MATCHING_RECIPE })

        expect(result).toEqual({ valid: true, already_recognized: true })
        // Only the recipe list GET ran — nothing was POSTed.
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('rejects an event whose payload is unavailable server-side instead of saving blind', async () => {
        // Retention TTL / events-table fallback strips the heavy AI columns; with both sides
        // undefined the normalizer reports recognized and any compiling YAML would save.
        const strippedEvent = generationEvent({ properties: {} })
        const { context, request } = createContext({ events: [strippedEvent] })

        const result = await parserRecipeCreate().handler(context, baseParams)

        expect(result.valid).toBe(false)
        expect(result.error).toContain('not available')
        expect(request).not.toHaveBeenCalled()
    })

    it('returns a not-found error when the event is absent from the trace', async () => {
        const { context, request } = createContext({ events: [generationEvent({ id: 'someone-else' })] })

        const result = await parserRecipeCreate().handler(context, baseParams)

        expect(result).toEqual({ valid: false, error: 'event not found in trace — re-check trace_id and event_uuid' })
        expect(request).not.toHaveBeenCalled()
    })

    it('reads $ai_input_state / $ai_output_state for span events', async () => {
        // Only the `_state` fields carry the sample; if the handler read `$ai_input`
        // instead, the input would be undefined and the recipe would fail to match.
        const spanEvent = generationEvent({
            event: '$ai_span',
            properties: {
                $ai_input_state: { acme_kind: 'q', acme_text: 'in' },
                $ai_output_state: { acme_kind: 'q', acme_text: 'out' },
            },
        })
        const request = vi.fn().mockResolvedValueOnce({ results: [] }).mockResolvedValueOnce({ id: 'recipe-span' })
        const { context } = createContext({ events: [spanEvent], request })

        const result = await parserRecipeCreate().handler(context, baseParams)

        expect(result).toEqual({ valid: true, recipe_id: 'recipe-span' })
    })

    it('reports a persistence failure as valid-but-unsaved so the agent does not rewrite', async () => {
        const request = vi.fn().mockResolvedValueOnce({ results: [] }).mockRejectedValueOnce(new Error('500 from API'))
        const { context } = createContext({ events: [generationEvent()], request })

        const result = await parserRecipeCreate().handler(context, baseParams)

        expect(result).toEqual({ valid: true, saved: false, error: '500 from API' })
    })
})
