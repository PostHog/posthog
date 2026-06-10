/**
 * RS256 JWT minting for the coding harness — matches `@posthog/agent`'s
 * server/jwt.ts: algorithm RS256, audience `posthog:sandbox_connection`, and
 * the `{run_id, task_id, team_id, user_id, distinct_id, mode}` claim set the
 * harness validates with its `JWT_PUBLIC_KEY` env.
 *
 * The supervisor generates an ephemeral keypair per session, hands the public
 * key to the container (env) and signs the connection token with the private
 * key. No external dep — node:crypto only.
 */

import { createSign, generateKeyPairSync } from 'node:crypto'

export const HARNESS_JWT_AUDIENCE = 'posthog:sandbox_connection'

export interface HarnessJwtClaims {
    run_id: string
    task_id: string
    team_id: number
    user_id: number
    distinct_id: string
    mode: 'interactive' | 'background'
}

export interface HarnessKeypair {
    /** SPKI PEM — passed to the container as JWT_PUBLIC_KEY. */
    publicKeyPem: string
    /** PKCS8 PEM — kept by the supervisor to sign connection tokens. */
    privateKeyPem: string
}

export function generateHarnessKeypair(): HarnessKeypair {
    const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
    return {
        publicKeyPem: publicKey.export({ type: 'spki', format: 'pem' }).toString(),
        privateKeyPem: privateKey.export({ type: 'pkcs8', format: 'pem' }).toString(),
    }
}

function b64url(input: Buffer | string): string {
    return Buffer.from(input).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** Mint an RS256 connection token the harness will accept. */
export function mintHarnessJwt(privateKeyPem: string, claims: HarnessJwtClaims, ttlSeconds = 3600): string {
    const header = { alg: 'RS256', typ: 'JWT' }
    const nowSeconds = Math.floor(Date.now() / 1000)
    const payload = { ...claims, aud: HARNESS_JWT_AUDIENCE, iat: nowSeconds, exp: nowSeconds + ttlSeconds }
    const signingInput = `${b64url(JSON.stringify(header))}.${b64url(JSON.stringify(payload))}`
    const signer = createSign('RSA-SHA256')
    signer.update(signingInput)
    return `${signingInput}.${b64url(signer.sign(privateKeyPem))}`
}
