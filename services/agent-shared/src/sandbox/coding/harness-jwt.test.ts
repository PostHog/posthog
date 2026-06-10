import { createVerify } from 'node:crypto'
import { describe, expect, it } from 'vitest'

import { generateHarnessKeypair, HARNESS_JWT_AUDIENCE, mintHarnessJwt } from './harness-jwt'

function decodeSegment(seg: string): Record<string, unknown> {
    return JSON.parse(Buffer.from(seg.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString())
}

describe('harness JWT', () => {
    const claims = {
        run_id: 'run-1',
        task_id: 'task-1',
        team_id: 7,
        user_id: 42,
        distinct_id: 'd-1',
        mode: 'background' as const,
    }

    it('mints an RS256 token with the audience + claims the harness validates', () => {
        const { privateKeyPem } = generateHarnessKeypair()
        const token = mintHarnessJwt(privateKeyPem, claims)
        const [h, p] = token.split('.')
        expect(decodeSegment(h)).toEqual({ alg: 'RS256', typ: 'JWT' })
        const payload = decodeSegment(p)
        expect(payload).toMatchObject({ ...claims, aud: HARNESS_JWT_AUDIENCE })
        expect(payload.exp).toBeGreaterThan(payload.iat as number)
    })

    it('produces a signature that verifies against the matching public key (RS256)', () => {
        const { publicKeyPem, privateKeyPem } = generateHarnessKeypair()
        const token = mintHarnessJwt(privateKeyPem, claims)
        const [h, p, sig] = token.split('.')
        const verifier = createVerify('RSA-SHA256')
        verifier.update(`${h}.${p}`)
        const ok = verifier.verify(publicKeyPem, Buffer.from(sig.replace(/-/g, '+').replace(/_/g, '/'), 'base64'))
        expect(ok).toBe(true)
    })

    it('a different keypair does NOT verify (tamper/wrong-key guard)', () => {
        const { privateKeyPem } = generateHarnessKeypair()
        const { publicKeyPem: otherPub } = generateHarnessKeypair()
        const token = mintHarnessJwt(privateKeyPem, claims)
        const [h, p, sig] = token.split('.')
        const verifier = createVerify('RSA-SHA256')
        verifier.update(`${h}.${p}`)
        expect(verifier.verify(otherPub, Buffer.from(sig.replace(/-/g, '+').replace(/_/g, '/'), 'base64'))).toBe(false)
    })
})
