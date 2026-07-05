import { describe, expect, it } from 'vitest'

import { createPlanTokenCodec, decodePlanToken, encodePlanToken, PLAN_TOKEN_TTL_SECONDS } from '@/lib/code-exec'
import { SignedStateCodec } from '@/lib/signed-state'

const KEY = Buffer.alloc(32, 0x42)
const FIXED_NOW = 1_700_000_000_000

function codecAt(nowMs: number): SignedStateCodec {
    return createPlanTokenCodec(KEY, { now: () => nowMs, randomNonce: () => 'nonce-fixed' })
}

describe('plan token', () => {
    it('round-trips planHash + scriptHash and surfaces the nonce and remaining TTL', async () => {
        const codec = codecAt(FIXED_NOW)
        const { token, nonce } = await encodePlanToken(codec, {
            sub: 'did-1',
            planHash: 'plan-abc',
            scriptHash: 'script-xyz',
        })
        const result = await decodePlanToken(codec, token, 'did-1')

        expect(result.ok).toBe(true)
        if (result.ok) {
            expect(result.planHash).toBe('plan-abc')
            expect(result.scriptHash).toBe('script-xyz')
            expect(result.nonce).toBe(nonce)
            // Fed straight into NonceLedger.consume for single-use enforcement.
            expect(result.secondsUntilExpiry).toBe(PLAN_TOKEN_TTL_SECONDS)
        }
    })

    it('maps an expired token to a dedicated expired result for auto-re-plan', async () => {
        const { token } = await encodePlanToken(codecAt(FIXED_NOW), {
            sub: 'did-1',
            planHash: 'p',
            scriptHash: 's',
        })
        // Decode with a clock past the 600s TTL.
        const result = await decodePlanToken(codecAt(FIXED_NOW + (PLAN_TOKEN_TTL_SECONDS + 1) * 1000), token, 'did-1')
        expect(result).toEqual({ ok: false, reason: 'expired' })
    })

    it('rejects a token minted for a different purpose', async () => {
        // A token signed under some other purpose must not verify as a plan token.
        const rawCodec = new SignedStateCodec(KEY, { now: () => FIXED_NOW, ttlSeconds: 600 })
        const { token } = await rawCodec.encode({
            sub: 'did-1',
            purpose: 'organization-enforce-2fa-update',
            payload: { planHash: 'p', scriptHash: 's' },
        })
        const result = await decodePlanToken(codecAt(FIXED_NOW), token, 'did-1')
        expect(result.ok).toBe(false)
        if (!result.ok) {
            expect(result.reason).toBe('invalid')
        }
    })

    it('rejects a token whose payload is not a plan payload', async () => {
        const rawCodec = new SignedStateCodec(KEY, { now: () => FIXED_NOW, ttlSeconds: 600 })
        const { token } = await rawCodec.encode({ sub: 'did-1', purpose: 'exec-apply', payload: { planHash: 'p' } })
        const result = await decodePlanToken(codecAt(FIXED_NOW), token, 'did-1')
        expect(result.ok).toBe(false)
        if (!result.ok) {
            expect(result.reason).toBe('invalid')
        }
    })
})
