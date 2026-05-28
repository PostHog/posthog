import { describe, expect, it, vi } from 'vitest'

import { ElicitationNotSupportedError } from '@/hono/session-bus'
import { requestConfirmation } from '@/tools/confirmation-runtime'
import type { Context } from '@/tools/types'

type RequestInputFn = NonNullable<Context['requestInput']>

function makeContext(requestInput: RequestInputFn | undefined): Context {
    // The runtime helper only touches `context.elicit`. Everything else is
    // stubbed to `null as never` — accessing them in the helper would be a
    // bug, and the test will surface it as a TypeError if it ever happens.
    const stub = null as unknown as never
    const ctx = {
        api: stub,
        cache: stub,
        env: stub,
        stateManager: stub,
        sessionManager: stub,
        getDistinctId: () => Promise.resolve('did'),
        trackEvent: () => Promise.resolve(),
    } as Context
    if (requestInput) {
        ctx.requestInput = requestInput
    }
    return ctx
}

/** Safely pull the text payload off a tool-error result. Narrows past noUncheckedIndexedAccess. */
function firstText(result: { content: ReadonlyArray<{ type: 'text'; text: string }> }): string {
    const first = result.content[0]
    if (!first) {
        throw new Error('tool result had no content entries')
    }
    return first.text
}

describe('requestConfirmation — no elicit available', () => {
    it.each([
        { policy: 'deny' as const, expectedKind: 'denied-no-elicit' as const },
        { policy: 'allow' as const, expectedKind: 'allowed-no-elicit' as const },
    ])(
        'routes to $expectedKind when context.elicit is undefined and policy is $policy',
        async ({ policy, expectedKind }) => {
            const outcome = await requestConfirmation(
                makeContext(undefined),
                {},
                {
                    message: 'Proceed?',
                    onNoElicit: policy,
                    actionLabel: 'enforce 2FA',
                }
            )
            expect(outcome.kind).toBe(expectedKind)
        }
    )

    it('deny includes an instructional message naming the action', async () => {
        const outcome = await requestConfirmation(
            makeContext(undefined),
            {},
            {
                message: 'Proceed?',
                onNoElicit: 'deny',
                actionLabel: 'enforce 2FA',
            }
        )
        if (outcome.kind !== 'denied-no-elicit') {
            throw new Error(`expected denied-no-elicit, got ${outcome.kind}`)
        }
        expect(outcome.result.isError).toBe(true)
        const text = firstText(outcome.result)
        expect(text).toContain('Enforce 2FA')
        expect(text).toContain('does not support')
    })
})

describe('requestConfirmation — elicit available', () => {
    it('emits an empty requestedSchema (no form fields, just action buttons)', async () => {
        const requestInput = vi.fn<RequestInputFn>(async () => ({ action: 'accept' as const }))
        await requestConfirmation(
            makeContext(requestInput),
            {},
            {
                message: 'Proceed?',
                onNoElicit: 'deny',
            }
        )
        expect(requestInput).toHaveBeenCalledWith(
            expect.objectContaining({
                requestedSchema: { type: 'object', properties: {} },
            })
        )
    })

    it('returns accepted when the user accepts', async () => {
        const requestInput = vi.fn<RequestInputFn>(async () => ({ action: 'accept' as const }))
        const outcome = await requestConfirmation(
            makeContext(requestInput),
            { id: 42 },
            {
                message: 'Delete {id}?',
                onNoElicit: 'deny',
            }
        )
        expect(outcome.kind).toBe('accepted')
        expect(requestInput).toHaveBeenCalledTimes(1)
        expect(requestInput).toHaveBeenCalledWith(expect.objectContaining({ message: 'Delete 42?' }))
    })

    it.each([
        { action: 'decline' as const, label: 'org delete', expectedWord: 'declined' },
        { action: 'cancel' as const, label: 'org delete', expectedWord: 'cancelled' },
    ])(
        'returns cancelled with a $expectedWord reason when the user $action',
        async ({ action, label, expectedWord }) => {
            const requestInput = vi.fn<RequestInputFn>(async () => ({ action }))
            const outcome = await requestConfirmation(
                makeContext(requestInput),
                {},
                {
                    message: 'Proceed?',
                    onNoElicit: 'deny',
                    actionLabel: label,
                }
            )
            if (outcome.kind !== 'cancelled') {
                throw new Error(`expected cancelled, got ${outcome.kind}`)
            }
            const text = firstText(outcome.result)
            expect(text).toContain(expectedWord)
            expect(text).toContain('Org delete')
        }
    )

    it.each([
        { policy: 'deny' as const, expectedKind: 'denied-no-elicit' as const },
        { policy: 'allow' as const, expectedKind: 'allowed-no-elicit' as const },
    ])(
        'treats runtime ElicitationNotSupportedError as the no-elicit branch ($policy)',
        async ({ policy, expectedKind }) => {
            const requestInput = vi.fn<RequestInputFn>(async () => {
                throw new ElicitationNotSupportedError(-32601, 'Method not found')
            })
            const outcome = await requestConfirmation(
                makeContext(requestInput),
                {},
                {
                    message: 'Proceed?',
                    onNoElicit: policy,
                }
            )
            expect(outcome.kind).toBe(expectedKind)
        }
    )

    it('propagates non-NotSupported errors (e.g. bus unhealthy) — does not swallow', async () => {
        const requestInput = vi.fn<RequestInputFn>(async () => {
            throw new Error('bus unhealthy')
        })
        await expect(
            requestConfirmation(
                makeContext(requestInput),
                {},
                {
                    message: 'Proceed?',
                    onNoElicit: 'deny',
                }
            )
        ).rejects.toThrow('bus unhealthy')
    })
})

describe('requestConfirmation — message templating', () => {
    it('interpolates {paramName} placeholders from params', async () => {
        const requestInput = vi.fn<RequestInputFn>(async () => ({ action: 'accept' as const }))
        await requestConfirmation(
            makeContext(requestInput),
            { orgId: 'acme', count: 3 },
            {
                message: 'Delete {count} items from {orgId}?',
                onNoElicit: 'deny',
            }
        )
        expect(requestInput).toHaveBeenCalledWith(expect.objectContaining({ message: 'Delete 3 items from acme?' }))
    })

    it('leaves unknown placeholders literal so authors notice missing keys', async () => {
        const requestInput = vi.fn<RequestInputFn>(async () => ({ action: 'accept' as const }))
        await requestConfirmation(
            makeContext(requestInput),
            {},
            {
                message: 'Delete {missing}?',
                onNoElicit: 'deny',
            }
        )
        expect(requestInput).toHaveBeenCalledWith(expect.objectContaining({ message: 'Delete {missing}?' }))
    })

    it('leaves null/undefined param values as literal placeholders, not the string "null"', async () => {
        const requestInput = vi.fn<RequestInputFn>(async () => ({ action: 'accept' as const }))
        await requestConfirmation(
            makeContext(requestInput),
            { id: null },
            {
                message: 'Action on {id}',
                onNoElicit: 'deny',
            }
        )
        expect(requestInput).toHaveBeenCalledWith(expect.objectContaining({ message: 'Action on {id}' }))
    })

    it('calls the builder when provided and uses its return value', async () => {
        const requestInput = vi.fn<RequestInputFn>(async () => ({ action: 'accept' as const }))
        const builder = vi.fn(async () => 'Built prompt')
        await requestConfirmation(
            makeContext(requestInput),
            { id: 1 },
            {
                builder,
                onNoElicit: 'deny',
            }
        )
        expect(builder).toHaveBeenCalledTimes(1)
        expect(requestInput).toHaveBeenCalledWith(expect.objectContaining({ message: 'Built prompt' }))
    })

    it('awaits sync builders too', async () => {
        const requestInput = vi.fn<RequestInputFn>(async () => ({ action: 'accept' as const }))
        await requestConfirmation(
            makeContext(requestInput),
            {},
            {
                builder: () => 'Sync prompt',
                onNoElicit: 'deny',
            }
        )
        expect(requestInput).toHaveBeenCalledWith(expect.objectContaining({ message: 'Sync prompt' }))
    })
})
