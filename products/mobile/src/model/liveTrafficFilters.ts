// Built-in session channels from DefaultChannelTypes in posthog/schema_enums.py. Projects can also define their own.
export const LIVE_CHANNEL_TYPES = [
    'Direct',
    'Organic Search',
    'Organic Social',
    'Organic Video',
    'Organic Shopping',
    'Paid Search',
    'Paid Social',
    'Paid Video',
    'Paid Shopping',
    'Paid Unknown',
    'Cross Network',
    'AI',
    'Referral',
    'Email',
    'Affiliate',
    'Push',
    'SMS',
    'Audio',
    'Unknown',
] as const

export const LIVE_DEVICE_TYPES = ['Mobile', 'Tablet', 'Desktop'] as const

export type LivePathMode = 'exact' | 'prefix'

export interface LiveTrafficFilters {
    excludeBots: boolean
    hostname: string
    /** Also holds exact path text. Selections from the original prefix-only control have no pathMode. */
    pathPrefix: string
    pathMode?: LivePathMode
    channelType?: string
    countryCode?: string
    deviceType?: string
    referringDomain?: string
}

export const DEFAULT_LIVE_TRAFFIC_FILTERS: Required<LiveTrafficFilters> = {
    excludeBots: false,
    hostname: '',
    pathPrefix: '',
    pathMode: 'exact',
    channelType: '',
    countryCode: '',
    deviceType: '',
    referringDomain: '',
}

export function normalizeLiveTrafficFilters(filters: LiveTrafficFilters): Required<LiveTrafficFilters> {
    const path = filters.pathPrefix.trim()
    return {
        excludeBots: filters.excludeBots,
        hostname: filters.hostname.trim().toLowerCase(),
        pathPrefix: path && !path.startsWith('/') ? `/${path}` : path,
        pathMode: path ? (filters.pathMode ?? 'prefix') : 'exact',
        channelType: filters.channelType?.trim() ?? '',
        countryCode: filters.countryCode?.trim().toUpperCase() ?? '',
        deviceType: filters.deviceType?.trim() ?? '',
        referringDomain: filters.referringDomain?.trim().toLowerCase() ?? '',
    }
}

export function liveTrafficFilterCount(filters: LiveTrafficFilters): number {
    return [
        filters.excludeBots,
        filters.hostname,
        filters.pathPrefix,
        filters.channelType,
        filters.countryCode,
        filters.deviceType,
        filters.referringDomain,
    ].filter(Boolean).length
}

export function hasLiveTrafficFilters(filters: LiveTrafficFilters): boolean {
    return liveTrafficFilterCount(filters) > 0
}
