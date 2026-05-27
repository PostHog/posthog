import { describe, expect, it, vi } from 'vitest'

import { ElicitationNotSupportedError } from '@/hono/session-bus'
import { requestConfirmation } from '@/tools/confirmation-runtime'
import type { Context } from '@/tools/types'

type ElicitFn = NonNullable<Context['elicit']>

function makeContext(elicit: ElicitFn | undefined): Context {
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
    if (elicit) {
        ctx.elicit = elicit
    }
    return ctx
}

describe('requestConfirmation — no elicit available', () => {
    it('returns denied-no-elicit when context.elicit is undefined and policy is deny', async () => {
        const outcome = await requestConfirmation(
            makeContext(undefined),
            {},
            {
                message: 'Proceed?',
                onNoElicit: 'deny',
                actionLabel: 'enforce 2FA',
            }
        )
        expect(outcome.kind).toBe('denied-no-elicit')
        if (outcome.kind === 'denied-no-elicit') {
            expect(outcome.result.isError).toBe(true)
            expect(outcome.result.content[0].text).toContain('Enforce 2FA')
            expect(outcome.result.content[0].text).toContain('does not support')
        }
    })

    it('returns allowed-no-elicit when context.elicit is undefined and policy is allow', async () => {
        const outcome = await requestConfirmation(
            makeContext(undefined),
            {},
            {
                message: 'Proceed?',
                onNoElicit: 'allow',
            }
        )
        expect(outcome.kind).toBe('allowed-no-elicit')
    })
})

describe('requestConfirmation — elicit available', () => {
    it('returns accepted when the user accepts', async () => {
        const elicit = vi.fn(async () => ({ action: 'accept' as const, content: { confirmed: true } }))
        const outcome = await requestConfirmation(
            makeContext(elicit),
            { id: 42 },
            {
                message: 'Delete {id}?',
                onNoElicit: 'deny',
            }
        )
        expect(outcome.kind).toBe('accepted')
        expect(elicit).toHaveBeenCalledTimes(1)
        const callArgs = elicit.mock.calls[0]![0]
        expect(callArgs.message).toBe('Delete 42?')
    })

    it('returns cancelled with a decline reason when the user declines', async () => {
        const elicit = vi.fn(async () => ({ action: 'decline' as const }))
        const outcome = await requestConfirmation(
            makeContext(elicit),
            {},
            {
                message: 'Proceed?',
                onNoElicit: 'deny',
                actionLabel: 'org delete',
            }
        )
        expect(outcome.kind).toBe('cancelled')
        if (outcome.kind === 'cancelled') {
            expect(outcome.result.content[0].text).toContain('declined')
            expect(outcome.result.content[0].text).toContain('Org delete')
        }
    })

    it('returns cancelled with a cancel reason when the user cancels', async () => {
        const elicit = vi.fn(async () => ({ action: 'cancel' as const }))
        const outcome = await requestConfirmation(
            makeContext(elicit),
            {},
            {
                message: 'Proceed?',
                onNoElicit: 'deny',
            }
        )
        expect(outcome.kind).toBe('cancelled')
        if (outcome.kind === 'cancelled') {
            expect(outcome.result.content[0].text).toContain('cancelled')
        }
    })

    it('treats runtime ElicitationNotSupportedError as the no-elicit branch (deny)', async () => {
        const elicit = vi.fn(async () => {
            throw new ElicitationNotSupportedError(-32601, 'Method not found')
        }) as unknown as ElicitFn
        const outcome = await requestConfirmation(
            makeContext(elicit),
            {},
            {
                message: 'Proceed?',
                onNoElicit: 'deny',
            }
        )
        expect(outcome.kind).toBe('denied-no-elicit')
    })

    it('treats runtime ElicitationNotSupportedError as the no-elicit branch (allow)', async () => {
        const elicit = vi.fn(async () => {
            throw new ElicitationNotSupportedError(-32601, 'Method not found')
        }) as unknown as ElicitFn
        const outcome = await requestConfirmation(
            makeContext(elicit),
            {},
            {
                message: 'Proceed?',
                onNoElicit: 'allow',
            }
        )
        expect(outcome.kind).toBe('allowed-no-elicit')
    })

    it('propagates non-NotSupported errors (e.g. bus unhealthy) — does not swallow', async () => {
        const elicit = vi.fn(async () => {
            throw new Error('bus unhealthy')
        }) as unknown as ElicitFn
        await expect(
            requestConfirmation(
                makeContext(elicit),
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
        const elicit = vi.fn(async () => ({ action: 'accept' as const }))
        await requestConfirmation(
            makeContext(elicit),
            { orgId: 'acme', count: 3 },
            {
                message: 'Delete {count} items from {orgId}?',
                onNoElicit: 'deny',
            }
        )
        expect(elicit.mock.calls[0]![0].message).toBe('Delete 3 items from acme?')
    })

    it('leaves unknown placeholders literal so authors notice missing keys', async () => {
        const elicit = vi.fn(async () => ({ action: 'accept' as const }))
        await requestConfirmation(
            makeContext(elicit),
            {},
            {
                message: 'Delete {missing}?',
                onNoElicit: 'deny',
            }
        )
        expect(elicit.mock.calls[0]![0].message).toBe('Delete {missing}?')
    })

    it('leaves null/undefined param values as literal placeholders, not the string "null"', async () => {
        const elicit = vi.fn(async () => ({ action: 'accept' as const }))
        await requestConfirmation(
            makeContext(elicit),
            { id: null },
            {
                message: 'Action on {id}',
                onNoElicit: 'deny',
            }
        )
        expect(elicit.mock.calls[0]![0].message).toBe('Action on {id}')
    })

    it('calls the builder when provided and uses its return value', async () => {
        const elicit = vi.fn(async () => ({ action: 'accept' as const }))
        const builder = vi.fn(async (_params, _ctx) => 'Built prompt')
        await requestConfirmation(
            makeContext(elicit),
            { id: 1 },
            {
                builder,
                onNoElicit: 'deny',
            }
        )
        expect(builder).toHaveBeenCalledTimes(1)
        expect(elicit.mock.calls[0]![0].message).toBe('Built prompt')
    })

    it('awaits sync builders too', async () => {
        const elicit = vi.fn(async () => ({ action: 'accept' as const }))
        await requestConfirmation(
            makeContext(elicit),
            {},
            {
                builder: () => 'Sync prompt',
                onNoElicit: 'deny',
            }
        )
        expect(elicit.mock.calls[0]![0].message).toBe('Sync prompt')
    })
})
