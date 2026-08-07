import { beforeEach, describe, expect, it } from 'vitest'

import {
    confirmedActionExecutesTotal,
    confirmedActionPreparesTotal,
    confirmedActionRefusalsTotal,
} from '@/hono/metrics'
import { NonceLedger, PayloadStash, SignedStateCodec } from '@/lib/signed-state'
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

function makeStash(): { stash: PayloadStash; store: Map<string, string>; quotas: Map<string, number> } {
    const store = new Map<string, string>()
    const quotas = new Map<string, number>()
    const stash = new PayloadStash({
        set: async (key, value, ..._args) => {
            const args = _args.map((a) => (typeof a === 'string' ? a.toUpperCase() : a))
            if (args.includes('NX') && store.has(key)) {
                return null
            }
            store.set(key, value)
            return 'OK'
        },
        get: async (key) => store.get(key) ?? null,
        del: async (...keys) => {
            let deleted = 0
            for (const key of keys) {
                if (store.delete(key)) {
                    deleted += 1
                }
            }
            return deleted
        },
        incrby: async (key, increment) => {
            const next = (quotas.get(key) ?? 0) + increment
            quotas.set(key, next)
            return next
        },
        expire: async () => 1,
        ttl: async () => 60,
    })
    return { stash, store, quotas }
}

describe('prepareConfirmedAction', () => {
    it('returns the canonical payload shape with a signed token', async () => {
        const codec = makeCodec()
        const { stash } = makeStash()
        const result = await prepareConfirmedAction(makeContext('did-1'), {
            args: { orgId: 'acme' },
            purpose: 'organization-enforce-2fa-update',
            actionLabel: 'enforce 2FA',
            messageTemplate: 'About to enable enforce 2FA on organization {orgId}.',
            codec,
            stash,
        })
        expect(result.confirmation_word).toBe(CONFIRMATION_WORD)
        expect(result.action).toBe('enforce 2FA')
        expect(result.message).toBe('About to enable enforce 2FA on organization acme.')
        expect(result.confirmation_hash.split('.')).toHaveLength(3)
        expect(result.next_steps).toContain('"confirm"')
    })

    it('keeps the hash small and constant-size regardless of args size', async () => {
        // The args live in the stash, not the token. If someone regresses to
        // signing them inline, a large payload (a scout body + files) makes
        // the hash tens of kilobytes that the model must relay verbatim —
        // this catches that by preparing ~200 KB of args.
        const codec = makeCodec()
        const { stash } = makeStash()
        const result = await prepareConfirmedAction(makeContext('did-1'), {
            args: { name: 'signals-scout-big', body: 'x'.repeat(200_000) },
            purpose: 'scout-create',
            actionLabel: 'create scout',
            messageTemplate: 'msg',
            codec,
            stash,
        })
        expect(result.confirmation_hash.length).toBeLessThan(1024)
    })

    it('refuses to stash a payload over the size cap', async () => {
        // Stashed payloads sit in shared Redis for the token TTL. Without
        // the cap, a caller at the rate limit can retain rate × TTL ×
        // request-size bytes and pressure eviction of session state.
        const codec = makeCodec()
        const { stash, store } = makeStash()
        await expect(
            prepareConfirmedAction(makeContext('did-1'), {
                args: { body: 'x'.repeat(1_100_000) },
                purpose: 'scout-create',
                actionLabel: 'create scout',
                messageTemplate: 'msg',
                codec,
                stash,
            })
        ).rejects.toThrow('too large')
        expect(store.size).toBe(0)
    })

    it('refuses to stash once the per-user window quota is exhausted', async () => {
        // Per-payload and per-request caps alone still let a caller at the
        // rate limit retain gigabytes within one token TTL; the aggregate
        // quota is what bounds that. Dropping it reopens the exposure.
        // Unique nonces per prepare — the shared makeCodec pins one nonce,
        // which would collide in the stash across repeated prepares.
        let nonceCounter = 0
        const codec = new SignedStateCodec(Buffer.alloc(32, 0x42), {
            now: () => 1_700_000_000_000,
            randomNonce: () => `nonce-${nonceCounter++}`,
            ttlSeconds: 300,
        })
        const { stash, store } = makeStash()
        const args = { body: 'x'.repeat(900_000) }
        for (let i = 0; i < 23; i++) {
            await prepareConfirmedAction(makeContext('did-1'), {
                args,
                purpose: 'scout-create',
                actionLabel: 'create scout',
                messageTemplate: 'msg',
                codec,
                stash,
            })
        }
        await expect(
            prepareConfirmedAction(makeContext('did-1'), {
                args,
                purpose: 'scout-create',
                actionLabel: 'create scout',
                messageTemplate: 'msg',
                codec,
                stash,
            })
        ).rejects.toThrow('too much pending confirmation data')
        expect(store.size).toBe(23)
    })

    it('leaves unknown placeholders literal so authors notice missing keys', async () => {
        const codec = makeCodec()
        const { stash } = makeStash()
        const result = await prepareConfirmedAction(makeContext(), {
            args: {},
            purpose: 'p',
            actionLabel: 'a',
            messageTemplate: 'Delete {missing}',
            codec,
            stash,
        })
        expect(result.message).toBe('Delete {missing}')
    })

    it('leaves non-scalar placeholders literal (no "[object Object]" in user prompts)', async () => {
        const codec = makeCodec()
        const { stash } = makeStash()
        const result = await prepareConfirmedAction(makeContext(), {
            args: { filters: { team: 1 }, tags: ['a', 'b'] },
            purpose: 'p',
            actionLabel: 'a',
            messageTemplate: 'Apply {filters} for {tags}',
            codec,
            stash,
        })
        expect(result.message).toBe('Apply {filters} for {tags}')
    })
})

describe('executeConfirmedAction', () => {
    function setup(): {
        codec: SignedStateCodec
        ledger: NonceLedger
        stash: PayloadStash
        store: Map<string, string>
    } {
        const codec = makeCodec()
        const { ledger } = makeLedger()
        const { stash, store } = makeStash()
        return { codec, ledger, stash, store }
    }

    async function mintToken(
        codec: SignedStateCodec,
        stash: PayloadStash,
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
            stash,
        })
        return result.confirmation_hash
    }

    it('verifies a fresh token and returns verifiedArgs', async () => {
        const { codec, ledger, stash } = setup()
        const hash = await mintToken(codec, stash, 'did-1', 'enforce-2fa', { orgId: 'acme' })
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: {
                [CONFIRMATION_HASH_ARG]: hash,
                [CONFIRMATION_WORD_ARG]: 'confirm',
            },
            purpose: 'enforce-2fa',
            codec,
            ledger,
            stash,
        })
        expect(outcome.ok).toBe(true)
        if (outcome.ok) {
            expect(outcome.verifiedArgs).toEqual({ orgId: 'acme' })
        }
    })

    it('refuses if the literal confirmation word is wrong', async () => {
        const { codec, ledger, stash } = setup()
        const hash = await mintToken(codec, stash, 'did-1', 'p', {})
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'yes' },
            purpose: 'p',
            codec,
            ledger,
            stash,
        })
        expect(outcome.ok).toBe(false)
        if (!outcome.ok) {
            expect(outcome.result.content[0]!.text).toContain('confirm')
        }
    })

    it('refuses on user mismatch', async () => {
        const { codec, ledger, stash } = setup()
        const hash = await mintToken(codec, stash, 'did-victim', 'p', {})
        const outcome = await executeConfirmedAction(makeContext('did-attacker'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'p',
            codec,
            ledger,
            stash,
        })
        expect(outcome.ok).toBe(false)
        if (!outcome.ok) {
            expect(outcome.result.content[0]!.text).toContain('different user')
        }
    })

    it('refuses on purpose mismatch', async () => {
        const { codec, ledger, stash } = setup()
        const hash = await mintToken(codec, stash, 'did-1', 'tool-A', {})
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'tool-B',
            codec,
            ledger,
            stash,
        })
        expect(outcome.ok).toBe(false)
        if (!outcome.ok) {
            expect(outcome.result.content[0]!.text).toContain('different action')
        }
    })

    it('refuses on replay of the same hash', async () => {
        const { codec, ledger, stash } = setup()
        const hash = await mintToken(codec, stash, 'did-1', 'p', { orgId: 'x' })
        const first = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'p',
            codec,
            ledger,
            stash,
        })
        expect(first.ok).toBe(true)
        const second = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'p',
            codec,
            ledger,
            stash,
        })
        expect(second.ok).toBe(false)
        if (!second.ok) {
            expect(second.result.content[0]!.text).toContain('already been used')
        }
    })

    it('refuses when the stashed payload does not match the signed digest', async () => {
        // Redis contents are not covered by the token signature — only the
        // digest binds them. Without this check, anything able to write the
        // stash key could swap in arbitrary args under a valid confirmation.
        const { codec, ledger, stash, store } = setup()
        const hash = await mintToken(codec, stash, 'did-1', 'p', { orgId: 'acme' })
        for (const key of store.keys()) {
            store.set(key, JSON.stringify({ args: { orgId: 'evil' }, scope: null }))
        }
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: hash, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'p',
            codec,
            ledger,
            stash,
        })
        expect(outcome.ok).toBe(false)
        if (!outcome.ok) {
            expect(outcome.result.content[0]!.text).toContain('does not match the signed digest')
        }
    })

    it('executes an inline-payload token once and refuses its replay via the ledger', async () => {
        // Mixed-version deploys: a server on the older token format signs
        // {args, scope} directly into the claim instead of stashing. The
        // newer execute path must still honor it exactly once.
        const { codec, ledger, stash } = setup()
        const { token } = await codec.encode({
            sub: 'did-1',
            purpose: 'p',
            payload: { args: { orgId: 'acme' }, scope: null },
        })
        const first = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: token, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'p',
            codec,
            ledger,
            stash,
        })
        expect(first.ok).toBe(true)
        if (first.ok) {
            expect(first.verifiedArgs).toEqual({ orgId: 'acme' })
        }
        const second = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: token, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'p',
            codec,
            ledger,
            stash,
        })
        expect(second.ok).toBe(false)
        if (!second.ok) {
            expect(second.result.content[0]!.text).toContain('already been used')
        }
    })

    it('refuses when the active scope no longer matches the scope bound at prepare time', async () => {
        // Cross-project replay: prepare while project A is active, then run
        // execute after switch-project made B active. The signed scope (A)
        // must not authorize the action against B.
        const { codec, ledger, stash } = setup()
        const prep = await prepareConfirmedAction(makeContext('did-1'), {
            args: { name: 'mrr' },
            purpose: 'metric-approve',
            actionLabel: 'approve metric',
            messageTemplate: 'msg',
            codec,
            stash,
            boundScope: { projectId: '1' },
        })
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: {
                [CONFIRMATION_HASH_ARG]: prep.confirmation_hash,
                [CONFIRMATION_WORD_ARG]: 'confirm',
            },
            purpose: 'metric-approve',
            codec,
            ledger,
            stash,
            expectedScope: { projectId: '2' },
        })
        expect(outcome.ok).toBe(false)
        if (!outcome.ok) {
            expect(outcome.result.content[0]!.text).toContain('different project or organization')
        }
    })

    it('succeeds when the active scope still matches the scope bound at prepare time', async () => {
        const { codec, ledger, stash } = setup()
        const prep = await prepareConfirmedAction(makeContext('did-1'), {
            args: { name: 'mrr' },
            purpose: 'metric-approve',
            actionLabel: 'approve metric',
            messageTemplate: 'msg',
            codec,
            stash,
            boundScope: { projectId: '1' },
        })
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: {
                [CONFIRMATION_HASH_ARG]: prep.confirmation_hash,
                [CONFIRMATION_WORD_ARG]: 'confirm',
            },
            purpose: 'metric-approve',
            codec,
            ledger,
            stash,
            expectedScope: { projectId: '1' },
        })
        expect(outcome.ok).toBe(true)
        if (outcome.ok) {
            expect(outcome.verifiedArgs).toEqual({ name: 'mrr' })
        }
    })

    it('refuses on tampered signature', async () => {
        const { codec, ledger, stash } = setup()
        const hash = await mintToken(codec, stash, 'did-1', 'p', {})
        const segs = hash.split('.')
        const tampered = `${segs[0]}.${segs[1]}.${segs[2]!.slice(0, -1)}A`
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: tampered, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'p',
            codec,
            ledger,
            stash,
        })
        expect(outcome.ok).toBe(false)
        if (!outcome.ok) {
            expect(outcome.result.content[0]!.text).toContain('signature is invalid')
        }
    })

    it('sources the ledger TTL from the codec clock, not the wall clock, for inline-payload tokens', async () => {
        // Pin the codec's clock 100s before exp. If the runtime ever
        // sources the TTL from the wall clock instead, the codec's fake
        // clock and real Date.now() will diverge by ~years and the
        // observed TTL will collapse to 1 — re-allowing replay against
        // a real Redis. Only inline-payload tokens touch the ledger.
        const codec = makeCodec() // ttlSeconds: 300, clock pinned 100s before exp
        const { stash } = makeStash()
        let observedTtl: number | undefined
        const ledger = new NonceLedger({
            set: async (_key, _value, ..._args) => {
                // arg order from NonceLedger.consume: ('EX', ttl, 'NX')
                observedTtl = _args[1] as number
                return 'OK'
            },
        })
        const { token } = await codec.encode({
            sub: 'did-1',
            purpose: 'tool-A',
            payload: { args: { x: 1 }, scope: null },
        })
        const outcome = await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: token, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'tool-A',
            codec,
            ledger,
            stash,
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
        const { stash } = makeStash()
        await prepareConfirmedAction(makeContext('did-1'), {
            args: {},
            purpose: 'tool-A',
            actionLabel: 'A',
            messageTemplate: 'msg',
            codec,
            stash,
        })
        expect(await metricValue(confirmedActionPreparesTotal, { tool: 'tool-A', status: 'ok' })).toBe(1)
    })

    it('increments executes_total ok on a successful execute', async () => {
        const codec = makeCodec()
        const { ledger } = makeLedger()
        const { stash } = makeStash()
        const prep = await prepareConfirmedAction(makeContext('did-1'), {
            args: { id: 'x' },
            purpose: 'tool-B',
            actionLabel: 'B',
            messageTemplate: 'msg',
            codec,
            stash,
        })
        await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: {
                [CONFIRMATION_HASH_ARG]: prep.confirmation_hash,
                [CONFIRMATION_WORD_ARG]: 'confirm',
            },
            purpose: 'tool-B',
            codec,
            ledger,
            stash,
        })
        expect(await metricValue(confirmedActionExecutesTotal, { tool: 'tool-B', status: 'ok' })).toBe(1)
    })

    it('increments refusals_total with the right reason label per failure mode', async () => {
        const codec = makeCodec()
        const { ledger } = makeLedger()
        const { stash } = makeStash()
        const prep = await prepareConfirmedAction(makeContext('did-1'), {
            args: {},
            purpose: 'tool-C',
            actionLabel: 'C',
            messageTemplate: 'msg',
            codec,
            stash,
        })
        // wrong word
        await executeConfirmedAction(makeContext('did-1'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: prep.confirmation_hash, [CONFIRMATION_WORD_ARG]: 'yes' },
            purpose: 'tool-C',
            codec,
            ledger,
            stash,
        })
        // user mismatch
        await executeConfirmedAction(makeContext('did-attacker'), {
            incomingArgs: { [CONFIRMATION_HASH_ARG]: prep.confirmation_hash, [CONFIRMATION_WORD_ARG]: 'confirm' },
            purpose: 'tool-C',
            codec,
            ledger,
            stash,
        })
        expect(await metricValue(confirmedActionRefusalsTotal, { tool: 'tool-C', reason: 'wrong_word' })).toBe(1)
        expect(await metricValue(confirmedActionRefusalsTotal, { tool: 'tool-C', reason: 'user_mismatch' })).toBe(1)
        expect(await metricValue(confirmedActionExecutesTotal, { tool: 'tool-C', status: 'refused' })).toBe(2)
    })
})
