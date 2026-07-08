import { beforeEach, describe, expect, it } from 'vitest'

import {
    confirmedActionExecutesTotal,
    confirmedActionPreparesTotal,
    confirmedActionRefusalsTotal,
} from '@/hono/metrics'
import { NonceLedger, SignedStateCodec } from '@/lib/signed-state'
import {
    CONFIRMATION_HASH_ARG,
    CONFIRMATION_WORD,
    CONFIRMATION_WORD_ARG,
    executeConfirmedAction,
    prepareConfirmedAction,
} from '@/tools/confirmed-action-runtime'
import type { Context } from '@/tools/types'

function makeContext(distinctId: string = 'did-1'): Context {
    const stub = null as unknown as never
    return {
        api: stub,
        cache: stub,
        env: stub,
        stateManager: stub,
        sessionManager: stub,
        getDistinctId: () => Promise.resolve(distinctId),
        trackEvent: () => Promise.resolve(),
    } as Context
}

function makeCodec(): SignedStateCodec {
    return new SignedStateCodec(Buffer.alloc(32, 0x42), {
        now: () => 1_700_000_000_000,
        randomNonce: () => 'nonce-fixed',
        ttlSeconds: 300,
    })
}

function makeLedger(): { ledger: NonceLedger; consumed: Set<string> } {
    const consumed = new Set<string>()
    const ledger = new NonceLedger({
        set: async (key, _value, ..._args) => {
            const args = _args.map((a) => (typeof a === 'string' ? a.toUpperCase() : a))
            const nx = args.includes('NX')
            if (nx && consumed.has(key)) {
                return null
            }
            consumed.add(key)
            return 'OK'
        },
    })
    return { ledger, consumed }
}

describe('prepareConfirmedAction', () => {
    it('returns the canonical payload shape with a signed token', async () => {
        const codec = makeCodec()
        const result = await prepareConfirmedAction(makeContext('did-1'), {
            args: { orgId: 'acme' },
            purpose: 'organization-enforce-2fa-update',
            actionLabel: 'enforce 2FA',
            messageTemplate: 'About to enable enforce 2FA on organization {orgId}.',
            codec,
        })
        expect(result.confirmation_word).toBe(CONFIRMATION_WORD)
        expect(result.action).toBe('enforce 2FA')
        expect(result.message).toBe('About to enable enforce 2FA on organization acme.')
        expect(result.confirmation_hash.split('.')).toHaveLength(3)
        expect(result.next_steps).toContain('"confirm"')
    })

    it('leaves unknown placeholders literal so authors notice missing keys', async () => {
        const codec = makeCodec()
        const result = await prepareConfirmedAction(makeContext(), {
            args: {},
            purpose: 'p',
            actionLabel: 'a',
            messageTemplate: 'Delete {missing}',
            codec,
        })
        expect(result.message).toBe('Delete {missing}')
    })

    it('leaves non-scalar placeholders literal (no "[object Object]" in user prompts)', async () => {
        const codec = makeCodec()
        const result = await prepareConfirmedAction(makeContext(), {
            args: { filters: { team: 1 }, tags: ['a', 'b'] },
            purpose: 'p',
            actionLabel: 'a',
            messageTemplate: 'Apply {filters} for {tags}',
            codec,
        })
        expect(result.message).toBe('Apply {filters} for {tags}')
    })
})

describe('executeConfirmedAction', () => {
    function setup(): { codec: SignedStateCodec; ledger: NonceLedger; consumed: Set<string> } {
        const codec = makeCodec()
        const { ledger, consumed } = makeLedger()
        return { codec, ledger, consumed }
    }

    async function mintToken(
        codec: SignedStateCodec,
        distinctId: string,
        purpose: string,
        payload: unknown
    ): Promise<string> {
        const ctx = makeContext(distinctId)
        const result = await prepareConfirmedAction(ctx, {
            args: payload as Record<string, unknown>,
            purpose,
            actionLabel: 'x',
            messageTemplate: 'msg',
            codec,
        })
        return result.confirmation_hash
    }

    it('verifies a fresh token and returns verifiedArgs', async () => {
        const { codec, ledger } = setup()
        const hash = await mintToken(codec, 'did-1', 'enforce-2fa', { orgId: 'acme' })
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: {
                [CONFIRMATION_HASH_ARG]: hash,
                [CONFIRMATION_WORD_ARG]: 'confirm',
                orgId: 'acme',
            },
            purpose: 'enforce-2fa',
            codec,
            ledger,
        })
        expect(outcome.ok).toBe(true)
        if (outcome.ok) {
            expect(outcome.verifiedArgs).toEqual({ orgId: 'acme' })
        }
    })

    it('refuses if the literal confirmation word is wrong', async () => {
        const { codec, ledger } = setup()
        const hash = await mintToken(codec, 'did-1', 'p', {})
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'yes' },
            purpose: 'p',
            codec,
            ledger,
        })
        expect(outcome.ok).toBe(false)
        if (!outcome.ok) {
            expect(outcome.result.content[0]!.text).toContain('confirm')
        }
    })

    it('refuses on user mismatch', async () => {
        const { codec, ledger } = setup()
        const hash = await mintToken(codec, 'did-victim', 'p', {})
        const outcome = await executeConfirmedAction(makeContext('did-attacker'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'p',
            codec,
            ledger,
        })
        expect(outcome.ok).toBe(false)
        if (!outcome.ok) {
            expect(outcome.result.content[0]!.text).toContain('different user')
        }
    })

    it('refuses on purpose mismatch', async () => {
        const { codec, ledger } = setup()
        const hash = await mintToken(codec, 'did-1', 'tool-A', {})
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'tool-B',
            codec,
            ledger,
        })
        expect(outcome.ok).toBe(false)
        if (!outcome.ok) {
            expect(outcome.result.content[0]!.text).toContain('different action')
        }
    })

    it('refuses on replay of the same hash', async () => {
        const { codec, ledger } = setup()
        const hash = await mintToken(codec, 'did-1', 'p', { orgId: 'x' })
        const first = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'confirm', orgId: 'x' },
            purpose: 'p',
            codec,
            ledger,
        })
        expect(first.ok).toBe(true)
        const second = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'confirm', orgId: 'x' },
            purpose: 'p',
            codec,
            ledger,
        })
        expect(second.ok).toBe(false)
        if (!second.ok) {
            expect(second.result.content[0]!.text).toContain('already been used')
        }
    })

    it('refuses on tampered signature', async () => {
        const { codec, ledger } = setup()
        const hash = await mintToken(codec, 'did-1', 'p', {})
        const segs = hash.split('.')
        const tampered = `${segs[0]}.${segs[1]}.${segs[2]!.slice(0, -1)}A`
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: tampered, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'p',
            codec,
            ledger,
        })
        expect(outcome.ok).toBe(false)
        if (!outcome.ok) {
            expect(outcome.result.content[0]!.text).toContain('signature is invalid')
        }
    })

    it('sources the ledger TTL from the codec clock, not the wall clock', async () => {
        // Pin the codec's clock 100s before exp. If the runtime ever
        // sources the TTL from the wall clock instead, the codec's fake
        // clock and real Date.now() will diverge by ~years and the
        // observed TTL will collapse to 1 — re-allowing replay against
        // a real Redis.
        const codec = makeCodec() // ttlSeconds: 300, clock pinned 100s before exp
        let observedTtl: number | undefined
        const ledger = new NonceLedger({
            set: async (_key, _value, ..._args) => {
                // arg order from NonceLedger.consume: ('EX', ttl, 'NX')
                observedTtl = _args[1] as number
                return 'OK'
            },
        })
        const hash = await mintToken(codec, 'did-1', 'tool-A', { x: 1 })
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'confirm', x: 1 },
            purpose: 'tool-A',
            codec,
            ledger,
        })
        expect(outcome.ok).toBe(true)
        expect(observedTtl).toBe(300)
    })
})

describe('confirmed-action metrics', () => {
    beforeEach(() => {
        // Counter values accumulate across tests in this process — reset to
        // make assertions order-independent.
        confirmedActionPreparesTotal.reset()
        confirmedActionExecutesTotal.reset()
        confirmedActionRefusalsTotal.reset()
    })

    function makeLedger(): NonceLedger {
        const consumed = new Set<string>()
        return new NonceLedger({
            set: async (key, _v, ..._args) => {
                if (consumed.has(key)) {
                    return null
                }
                consumed.add(key)
                return 'OK'
            },
        })
    }

    async function metricValue(
        counter:
            | typeof confirmedActionPreparesTotal
            | typeof confirmedActionExecutesTotal
            | typeof confirmedActionRefusalsTotal,
        labels: Record<string, string>
    ): Promise<number> {
        const json = await counter.get()
        return (
            json.values.find((v) =>
                Object.entries(labels).every(([k, val]) => (v.labels as Record<string, string>)[k] === val)
            )?.value ?? 0
        )
    }

    it('increments prepares_total on a successful prepare', async () => {
        const codec = makeCodec()
        await prepareConfirmedAction(makeContext('did-1'), {
            args: {},
            purpose: 'tool-A',
            actionLabel: 'A',
            messageTemplate: 'msg',
            codec,
        })
        expect(await metricValue(confirmedActionPreparesTotal, { tool: 'tool-A', status: 'ok' })).toBe(1)
    })

    it('increments executes_total ok on a successful execute', async () => {
        const codec = makeCodec()
        const ledger = makeLedger()
        const prep = await prepareConfirmedAction(makeContext('did-1'), {
            args: { id: 'x' },
            purpose: 'tool-B',
            actionLabel: 'B',
            messageTemplate: 'msg',
            codec,
        })
        await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: {
                [CONFIRMATION_HASH_ARG]: prep.confirmation_hash,
                [CONFIRMATION_WORD_ARG]: 'confirm',
                id: 'x',
            },
            purpose: 'tool-B',
            codec,
            ledger,
        })
        expect(await metricValue(confirmedActionExecutesTotal, { tool: 'tool-B', status: 'ok' })).toBe(1)
    })

    it('increments refusals_total with the right reason label per failure mode', async () => {
        const codec = makeCodec()
        const ledger = makeLedger()
        const prep = await prepareConfirmedAction(makeContext('did-1'), {
            args: {},
            purpose: 'tool-C',
            actionLabel: 'C',
            messageTemplate: 'msg',
            codec,
        })
        // wrong word
        await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: prep.confirmation_hash, [CONFIRMATION_WORD_ARG]: 'yes' },
            purpose: 'tool-C',
            codec,
            ledger,
        })
        // user mismatch
        await executeConfirmedAction(makeContext('did-attacker'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: prep.confirmation_hash, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'tool-C',
            codec,
            ledger,
        })
        expect(await metricValue(confirmedActionRefusalsTotal, { tool: 'tool-C', reason: 'wrong_word' })).toBe(1)
        expect(await metricValue(confirmedActionRefusalsTotal, { tool: 'tool-C', reason: 'user_mismatch' })).toBe(1)
        expect(await metricValue(confirmedActionExecutesTotal, { tool: 'tool-C', status: 'refused' })).toBe(2)
    })
})
