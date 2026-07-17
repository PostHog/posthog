import type { CloudRegion } from '../shared/ipc.ts'

export const CLOUD_HOSTS: Record<Exclude<CloudRegion, 'custom'>, string> = {
    us: 'https://us.posthog.com',
    eu: 'https://eu.posthog.com',
}

/** Normalizes a user-entered host: adds https://, strips paths and trailing slashes. */
export function normalizeCustomHost(input: string): string | null {
    let candidate = input.trim()
    if (!candidate) {
        return null
    }
    if (!/^https?:\/\//i.test(candidate)) {
        candidate = `https://${candidate}`
    }
    try {
        const url = new URL(candidate)
        if (url.protocol !== 'https:' && url.protocol !== 'http:') {
            return null
        }
        return url.origin
    } catch {
        return null
    }
}

export function resolveApiHost(region: CloudRegion, customHost: string): string | null {
    if (region === 'custom') {
        return normalizeCustomHost(customHost)
    }
    return CLOUD_HOSTS[region]
}
