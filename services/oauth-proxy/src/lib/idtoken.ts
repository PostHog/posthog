import { type JWK, SignJWT, calculateJwkThumbprint, createRemoteJWKSet, exportJWK, importPKCS8, jwtVerify } from 'jose'

import { type Region, baseUrlForRegion } from './constants'

/**
 * ID token re-issuance.
 *
 * A regional server signs an ID token with its own issuer and with the regional `client_id` as
 * the audience. A client that discovered this proxy knows neither value, so both claims fail the
 * checks a conformant OpenID relying party runs. See the README section on ID tokens.
 */

export interface SigningKeyEnv {
    /** PKCS#8 PEM that signs the ID tokens this proxy issues. See the README for rotation. */
    OIDC_SIGNING_KEY?: string
    /** Published in JWKS but never used for signing, so a rotation can retire a key without
     * invalidating the tokens it already signed. Mirrors `OIDC_RSA_PRIVATE_KEY_INACTIVE_*`. */
    OIDC_SIGNING_KEY_INACTIVE_1?: string
    OIDC_SIGNING_KEY_INACTIVE_2?: string
}

interface ProxyKey {
    privateKey: CryptoKey
    publicJwk: JWK
    kid: string
}

export class IdTokenReissueError extends Error {}

const SIGNING_ALGORITHM = 'RS256'

type KeySlot = 'active' | 'inactive_1' | 'inactive_2'

const keyCache = new Map<KeySlot, Promise<ProxyKey>>()

const regionalJwks = new Map<Region, ReturnType<typeof createRemoteJWKSet>>()

/** Cloudflare's secret editor stores a PEM as a single line, so accept the escaped form too. */
function normalizePem(raw: string): string {
    return raw.replace(/\\n/g, '\n').trim()
}

async function loadKey(slot: KeySlot, pem: string): Promise<ProxyKey> {
    const cached = keyCache.get(slot)
    if (cached) {
        return cached
    }

    const normalized = normalizePem(pem)

    const loading = (async (): Promise<ProxyKey> => {
        // Exportable because the public half of this key has to be derived for the JWKS document.
        const privateKey = await importPKCS8(normalized, SIGNING_ALGORITHM, { extractable: true })
        const fullJwk = await exportJWK(privateKey)
        const publicJwk: JWK = { kty: fullJwk.kty, n: fullJwk.n, e: fullJwk.e }
        const kid = await calculateJwkThumbprint(publicJwk)
        return { privateKey, publicJwk, kid }
    })()

    keyCache.set(slot, loading)
    return loading
}

async function activeSigningKey(env: SigningKeyEnv): Promise<ProxyKey> {
    if (!env.OIDC_SIGNING_KEY) {
        throw new IdTokenReissueError('No signing key is configured')
    }

    return loadKey('active', env.OIDC_SIGNING_KEY)
}

export async function proxyJwks(env: SigningKeyEnv): Promise<JWK[]> {
    const pems: [KeySlot, string | undefined][] = [
        ['active', env.OIDC_SIGNING_KEY],
        ['inactive_1', env.OIDC_SIGNING_KEY_INACTIVE_1],
        ['inactive_2', env.OIDC_SIGNING_KEY_INACTIVE_2],
    ]
    const keys = await Promise.all(pems.filter(([, pem]) => pem).map(([slot, pem]) => loadKey(slot, pem as string)))

    return keys.map((key) => ({ ...key.publicJwk, alg: SIGNING_ALGORITHM, use: 'sig', kid: key.kid }))
}

function jwksForRegion(region: Region): ReturnType<typeof createRemoteJWKSet> {
    const cached = regionalJwks.get(region)
    if (cached) {
        return cached
    }

    const jwks = createRemoteJWKSet(new URL('/.well-known/jwks.json', baseUrlForRegion(region)))
    regionalJwks.set(region, jwks)
    return jwks
}

/** Verification runs first so the proxy never signs claims it has not checked. */
export async function reissueIdToken(
    idToken: string,
    options: { region: Region; issuer: string; audience: string | null; env: SigningKeyEnv }
): Promise<string> {
    const active = await activeSigningKey(options.env)

    let payload: Record<string, unknown>
    try {
        const verified = await jwtVerify(idToken, jwksForRegion(options.region))
        payload = verified.payload as Record<string, unknown>
    } catch (error) {
        throw new IdTokenReissueError(
            `Regional ID token failed verification: ${error instanceof Error ? error.message : 'unknown error'}`
        )
    }

    const { iss: _iss, aud: upstreamAudience, jti: _jti, iat, exp, ...claims } = payload
    if (typeof iat !== 'number' || typeof exp !== 'number') {
        throw new IdTokenReissueError('Regional ID token is missing iat or exp')
    }

    const audience = options.audience ?? upstreamAudience
    if (typeof audience !== 'string') {
        throw new IdTokenReissueError('No audience available for the re-issued ID token')
    }

    return new SignJWT(claims)
        .setProtectedHeader({ alg: SIGNING_ALGORITHM, kid: active.kid })
        .setIssuer(options.issuer)
        .setAudience(audience)
        .setIssuedAt(iat)
        .setExpirationTime(exp)
        .setJti(crypto.randomUUID())
        .sign(active.privateKey)
}
