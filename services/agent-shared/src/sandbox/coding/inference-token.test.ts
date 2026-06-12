import { describe, expect, it } from 'vitest'

import { INTERNAL_JWT_AUDIENCE, mintInternalJwt } from '../../runtime/internal-jwt'
import { mintInferenceProxyToken, verifyInferenceProxyToken } from './inference-token'

const KEY = 'test-signing-key'

describe('inference proxy token', () => {
    it('round-trips the session id', async () => {
        const token = await mintInferenceProxyToken({ sessionId: 'sess-1', signingKey: KEY, ttlSec: 60 })
        const verified = await verifyInferenceProxyToken({ token, signingKey: KEY })
        expect(verified).toEqual({ sessionId: 'sess-1' })
    })

    it('rejects a token signed with a different key', async () => {
        const token = await mintInferenceProxyToken({ sessionId: 'sess-1', signingKey: 'other', ttlSec: 60 })
        await expect(verifyInferenceProxyToken({ token, signingKey: KEY })).rejects.toThrow(/verify failed/)
    })

    it('rejects an expired token', async () => {
        const token = await mintInferenceProxyToken({ sessionId: 'sess-1', signingKey: KEY, ttlSec: -10 })
        await expect(verifyInferenceProxyToken({ token, signingKey: KEY })).rejects.toThrow(/verify failed/)
    })

    it('rejects an internal JWT minted for a different audience (no cross-surface replay)', async () => {
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
            signingKey: KEY,
            claims: { session_id: 'sess-1' },
        })
        await expect(verifyInferenceProxyToken({ token, signingKey: KEY })).rejects.toThrow(/verify failed/)
    })

    it('rejects a token without a session_id claim', async () => {
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.INGRESS_INFERENCE,
            signingKey: KEY,
        })
        await expect(verifyInferenceProxyToken({ token, signingKey: KEY })).rejects.toThrow(/session_id/)
    })
})
