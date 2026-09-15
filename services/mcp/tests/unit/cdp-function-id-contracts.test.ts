import { describe, expect, it } from 'vitest'

import { formatInputValidationError } from '@/tools/exec'
import { GENERATED_TOOLS } from '@/tools/generated/cdp_functions'

// The revision tools identify a function by UUID, but an agent doing rollback work starts from a
// destination name. Production traces show it calling with no `id` at all, or with another
// spelling of it, and giving up on the rejection. Each tool therefore names cdp-functions-list as
// the source in its `id` description — which the missing-parameter rejection echoes back — and
// accepts the spellings agents reach for.
describe('cdp function id contracts', () => {
    const FUNCTION_ID = '0198f0aa-1c2d-7000-8000-0123456789ab'
    const ALIASES = [
        'function_id',
        'functionId',
        'hog_function_id',
        'hogFunctionId',
        'destination_id',
        'destinationId',
    ] as const

    describe.each([
        ['cdp-functions-list-revisions', {}],
        ['cdp-functions-get-revision', { version: 3 }],
        ['cdp-functions-restore-revision', { version: 3 }],
    ])('%s', (toolName, otherParams) => {
        const schema = GENERATED_TOOLS[toolName]!().schema

        it.each(['id', ...ALIASES])('normalizes %s to `id`', (key) => {
            const result = schema.safeParse({ [key]: FUNCTION_ID, ...otherParams })

            expect(result.success).toBe(true)
            const data = result.data as Record<string, unknown>
            expect(data.id).toBe(FUNCTION_ID)
            for (const alias of ALIASES) {
                expect(data).not.toHaveProperty(alias)
            }
        })

        it('keeps `id` when the caller sends both spellings', () => {
            const result = schema.safeParse({ id: FUNCTION_ID, destination_id: 'other', ...otherParams })

            expect((result.data as Record<string, unknown>).id).toBe(FUNCTION_ID)
        })

        it('names cdp-functions-list when the caller holds no id', () => {
            const result = schema.safeParse(otherParams, { reportInput: true })

            expect(result.success).toBe(false)
            const message = formatInputValidationError(toolName, result.error!, otherParams, schema)
            expect(message).toContain('missing required parameter: id')
            expect(message).toContain('cdp-functions-list')
        })
    })
})
