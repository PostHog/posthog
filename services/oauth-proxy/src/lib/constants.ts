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
