import { apiJson } from './client'

export type PushPlatform = 'ios' | 'android'

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
