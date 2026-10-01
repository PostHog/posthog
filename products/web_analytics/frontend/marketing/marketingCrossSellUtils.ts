import { DefaultChannelTypes, WebStatsBreakdown, WebStatsTableQueryResponse } from '~/queries/schema/schema-general'

const PAID_CHANNELS = new Set<string>([
    DefaultChannelTypes.PaidSearch,
    DefaultChannelTypes.PaidSocial,
    DefaultChannelTypes.PaidVideo,
    DefaultChannelTypes.PaidShopping,
    DefaultChannelTypes.PaidUnknown,
    DefaultChannelTypes.CrossNetwork,
])

export function supportsMarketingCrossSell(breakdown: WebStatsBreakdown): boolean {
    return [
        WebStatsBreakdown.InitialChannelType,
        WebStatsBreakdown.InitialUTMSource,
        WebStatsBreakdown.InitialUTMMedium,
        WebStatsBreakdown.InitialUTMCampaign,
        WebStatsBreakdown.InitialUTMContent,
        WebStatsBreakdown.InitialUTMTerm,
        WebStatsBreakdown.InitialUTMSourceMediumCampaign,
    ].includes(breakdown)
}

export function hasPaidChannelTraffic(response: WebStatsTableQueryResponse | null): boolean {
    const visitorsIndex = response?.columns?.indexOf('context.columns.visitors') ?? -1
    if (visitorsIndex < 0) {
        return false
    }
    return !!response?.results.some((row) => {
        if (!Array.isArray(row) || !PAID_CHANNELS.has(row[0])) {
            return false
        }
        const visitors = row[visitorsIndex]
        // Comparison-only rows do not establish paid traffic in the selected period.
        return Array.isArray(visitors) && typeof visitors[0] === 'number' && visitors[0] > 0
    })
}
