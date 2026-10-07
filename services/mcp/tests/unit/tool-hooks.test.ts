import { describe, expect, it, vi } from 'vitest'

import { withToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

const context = {} as Context

describe('withToolHooks', () => {
    it('runs beforeRequest, the handler with its params, then afterResponse', async () => {
        const handler = vi.fn(async (_context: Context, params: { n: number }) => ({ doubled: params.n * 2 }))
        const wrapped = withToolHooks(
            {
                beforeRequest: (_context, params) => ({ n: params.n + 1 }),
                afterResponse: (_context, params, result) => ({ result, sent: params }),
            },
            handler
        )

        await expect(wrapped(context, { n: 1 })).resolves.toEqual({ result: { doubled: 4 }, sent: { n: 2 } })
    })

    it.each([
        { name: 'onError returns a result', onError: () => 'handled', expected: 'handled' },
        {
            name: 'onError rethrows',
            onError: (_context: Context, _params: unknown, error: unknown) => {
                throw error
            },
            expected: undefined,
        },
        { name: 'no onError', onError: undefined, expected: undefined },
    ])('request failure: $name', async ({ onError, expected }) => {
        const failure = new Error('boom')
        const wrapped = withToolHooks({ onError }, async () => {
            throw failure
        })

        if (expected === undefined) {
            await expect(wrapped(context, {})).rejects.toBe(failure)
        } else {
            await expect(wrapped(context, {})).resolves.toBe(expected)
        }
    })

    it('does not send the request or call onError when beforeRequest fails', async () => {
        const handler = vi.fn()
        const onError = vi.fn()
        const wrapped = withToolHooks(
            {
                beforeRequest: () => {
                    throw new Error('lookup failed')
                },
                onError,
            },
            handler
        )

        await expect(wrapped(context, {})).rejects.toThrow('lookup failed')
        expect(handler).not.toHaveBeenCalled()
        expect(onError).not.toHaveBeenCalled()
    })
})
