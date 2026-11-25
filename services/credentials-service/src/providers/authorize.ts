// The authorize URL, built the way `OauthIntegration.authorize_url` builds it today. Django owns the
// browser leg and builds this URL from the generated catalogue, so the template here is what the
// catalogue carries. The builder exists so the template can be checked against Python's URLs.

import { createHash } from 'node:crypto'

import type { AuthorizeSpec } from './schema'

/** The values that Django fills into an authorize parameter. Any other parameter value is a literal. */
export const AUTHORIZE_PLACEHOLDERS = ['{client_id}', '{redirect_uri}', '{state}', '{code_challenge}'] as const

export type AuthorizeParam = readonly [name: string, value: string]

export interface AuthorizeInput {
    clientId: string
    redirectUri: string
    /** The urlencoded state payload. The builder hex-encodes it for an `opaqueState` provider. */
    state: string
    /** Required when the spec uses PKCE. */
    codeChallenge?: string
    /** Values for the URL placeholders, by placeholder name. */
    urlValues?: Readonly<Record<string, string>>
}

/** The ordered parameter template: the spec's own list, or the standard OAuth set plus its extras. */
export function authorizeParams(authorize: AuthorizeSpec): AuthorizeParam[] {
    if (authorize.params) {
        return authorize.params
    }
    const params: AuthorizeParam[] = [
        ['client_id', '{client_id}'],
        ['scope', authorize.scope],
        ['redirect_uri', '{redirect_uri}'],
        ['response_type', 'code'],
        ['state', '{state}'],
        ...(authorize.extraParams ?? []),
    ]
    if (authorize.pkce) {
        params.push(['code_challenge', '{code_challenge}'], ['code_challenge_method', 'S256'])
    }
    return params
}

export function buildAuthorizeUrl(authorize: AuthorizeSpec, input: AuthorizeInput): string {
    if (authorize.pkce && !input.codeChallenge) {
        throw new Error('this provider uses PKCE, so the authorize URL needs a code challenge')
    }
    const state = authorize.opaqueState ? Buffer.from(input.state, 'utf8').toString('hex') : input.state
    const fill: Record<string, string | undefined> = {
        '{client_id}': input.clientId,
        '{redirect_uri}': input.redirectUri,
        '{state}': state,
        '{code_challenge}': input.codeChallenge,
    }
    const pairs = authorizeParams(authorize).map(([name, value]): AuthorizeParam => [name, fill[value] ?? value])
    const url = authorize.url.replace(/\{([a-z_]+)\}/g, (_, name: string) => {
        const value = input.urlValues?.[name]
        if (!value) {
            throw new Error(`no value for the authorize URL placeholder {${name}}`)
        }
        return encodeURIComponent(value)
    })
    return `${url}?${pythonUrlencode(pairs)}`
}

/** The S256 code challenge of RFC 7636: base64url of the SHA-256 of the verifier, with no padding. */
export function pkceChallenge(verifier: string): string {
    return createHash('sha256').update(verifier, 'utf8').digest('base64url')
}

/**
 * Python's `urllib.parse.urlencode`, so a URL built here is byte-identical to one Django builds.
 * `URLSearchParams` differs: it encodes `~` and leaves `*`, `!`, `'`, `(` and `)` as they are.
 */
export function pythonUrlencode(pairs: readonly AuthorizeParam[]): string {
    return pairs.map(([name, value]) => `${quotePlus(name)}=${quotePlus(value)}`).join('&')
}

function quotePlus(value: string): string {
    return encodeURIComponent(value)
        .replace(/[!'()*]/g, (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`)
        .replace(/%20/g, '+')
}
