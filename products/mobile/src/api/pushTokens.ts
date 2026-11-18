import { ApiError, apiJson, NotSignedInError } from './client'
import { transport } from './transport'

export type PushPlatform = 'ios' | 'android'

/** The host and access token of one account, read from that account's own token slot. */
export interface AccountCredentials {
    host: string
    accessToken: string
}

// Needs `user:write`. The server upserts on (user, token), so a call on every launch only refreshes `last_seen_at`.
export async function registerPushToken(
    token: string,
    platform: PushPlatform,
    init: { signal?: AbortSignal } = {}
): Promise<void> {
    await apiJson('/api/users/@me/push_tokens/', { method: 'POST', json: { token, platform }, ...init })
}

/** Removes the token for the signed-in user. The server returns 204 even when nothing matched. */
export async function unregisterPushToken(token: string, init: { signal?: AbortSignal } = {}): Promise<void> {
    await apiJson('/api/users/@me/push_tokens/unregister/', { method: 'POST', json: { token }, ...init })
}

/**
 * Removes the token for the account that `credentials` belong to, on that account's host. It never reads the active
 * session, so a request for an account that is no longer active cannot carry another account's token or host.
 */
export async function unregisterPushTokenFor(
    credentials: AccountCredentials,
    token: string,
    init: { signal?: AbortSignal } = {}
): Promise<void> {
    const response = await transport(() =>
        fetch(`${credentials.host.replace(/\/+$/, '')}/api/users/@me/push_tokens/unregister/`, {
            method: 'POST',
            signal: init.signal,
            headers: {
                Accept: 'application/json',
                Authorization: `Bearer ${credentials.accessToken}`,
                'Content-Type': 'application/json',
                'X-PostHog-Client-Platform': 'mobile',
            },
            body: JSON.stringify({ token }),
        })
    )
    if (response.status === 401) {
        throw new NotSignedInError()
    }
    if (!response.ok) {
        throw new ApiError(response.status, undefined, response.headers)
    }
}
