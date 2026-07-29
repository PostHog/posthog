import { beforeEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { handleToolError, ToolInputValidationError, wrapError } from '@/lib/errors'

const captureException = vi.fn()
vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException }),
}))

/** Shape of the schemas that leaked: a nested union whose ZodError.message is the
 *  JSON-stringified issue array, hundreds of lines of `invalid_union` objects. */
const seriesSchema = z.object({ series: z.array(z.object({ math: z.enum(['total', 'dau']) })) })

function thrownZodError(): unknown {
    try {
        seriesSchema.parse({ series: [{ math: 'nonsense' }] })
    } catch (error) {
        return error
    }
    throw new Error('expected the schema to reject')
}

describe('handleToolError with ToolInputValidationError', () => {
    beforeEach(() => {
        captureException.mockClear()
    })

    it('returns the pre-formatted message verbatim without capturing an exception', () => {
        const error = new ToolInputValidationError('Invalid input for "action-get": missing required parameter: id')

        const result = handleToolError(error, 'action-get')

        expect(result.isError).toBe(true)
        const [content] = result.content as Array<{ type: string; text: string }>
        expect(content?.type).toBe('text')
        expect(content?.text).toBe(
            'Error: [action-get]: Invalid input for "action-get": missing required parameter: id'
        )
        expect(captureException).not.toHaveBeenCalled()
    })

    // A `.parse()` inside a tool handler throws a ZodError no validation gate caught.
    // It used to reach the fallthrough, which returned `error.message` — the raw issue
    // JSON — to the model and captured it, so the dump landed in the user's chat.
    it.each([
        ['thrown directly', (error: unknown) => error],
        ['wrapped as a cause', (error: unknown) => wrapError('Failed to run the query', error)],
    ])('humanizes a stray ZodError %s', (_label, wrap) => {
        const result = handleToolError(wrap(thrownZodError()), 'query-trends')

        expect(result.isError).toBe(true)
        const [content] = result.content as Array<{ type: string; text: string }>
        expect(content?.text).toContain('Invalid input for "query-trends"')
        expect(content?.text).toContain('series.0.math')
        expect(content?.text).not.toContain('"code"')
        expect(captureException).not.toHaveBeenCalled()
    })
})
