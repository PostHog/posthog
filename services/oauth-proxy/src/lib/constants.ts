export type Region = 'us' | 'eu'

export const POSTHOG_US_BASE_URL = 'https://us.posthog.com'
export const POSTHOG_EU_BASE_URL = 'https://eu.posthog.com'

export const REGION_BASE_URLS: Record<Region, string> = {
    us: POSTHOG_US_BASE_URL,
    eu: POSTHOG_EU_BASE_URL,
}

export function toRegion(value: string | undefined | null): Region {
    return value?.toLowerCase() === 'eu' ? 'eu' : 'us'
}

export function baseUrlForRegion(region: Region): string {
    return REGION_BASE_URLS[region]
}

export function regionForBaseUrl(baseUrl: string): Region | null {
    const match = Object.entries(REGION_BASE_URLS).find(([, url]) => url === baseUrl)
    return match ? (match[0] as Region) : null
}

export function proxyOrigin(request: Request): string {
    return new URL(request.url).origin
}

export const CALLBACK_PATH = '/oauth/callback/'

/** Registered at DCR. A region accepts each client's own path under it, see OAuthApplication.redirect_uri_allowed. */
export function sharedCallbackUrl(origin: string): string {
    return `${origin}${CALLBACK_PATH}`
}

export function clientCallbackUrl(origin: string, regionalClientId: string): string {
    return `${sharedCallbackUrl(origin)}${encodeURIComponent(regionalClientId)}/`
}

/** Whether a path has the shape `clientCallbackUrl` builds: one segment under the shared callback. */
export function isClientCallbackPath(pathname: string): boolean {
    return pathname.startsWith(CALLBACK_PATH) && /^[^/]+\/$/.test(pathname.slice(CALLBACK_PATH.length))
}
