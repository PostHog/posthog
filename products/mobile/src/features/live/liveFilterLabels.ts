import { countryName } from '@/model/adapters/webAnalyticsBreakdowns'
import type { LiveTrafficFilters } from '@/model/liveTrafficFilters'

export const LIVE_FILTER_FIELDS = {
    hostname: 'Hostname',
    pathPrefix: 'Page path',
    channelType: 'Channel',
    referringDomain: 'Entry referring domain',
    countryCode: 'Country',
    deviceType: 'Device type',
} as const

export type LiveFilterField = keyof typeof LIVE_FILTER_FIELDS

export function liveFilterValue(field: LiveFilterField, filters: LiveTrafficFilters): string {
    const value = filters[field]
    if (!value) return ''
    if (field === 'countryCode') return countryName(value)
    if (field === 'referringDomain' && value === '$direct') return 'Direct traffic'
    if (field === 'pathPrefix')
        return filters.pathMode === 'exact' ? `Path is ${value}` : `Paths starting with ${value}`
    return value
}
