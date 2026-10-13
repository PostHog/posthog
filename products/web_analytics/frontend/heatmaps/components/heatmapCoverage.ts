import type { HeatmapFilters, HeatmapKind } from 'lib/components/heatmaps/types'
import { calculateViewportRange } from 'lib/components/IframedToolbarBrowser/utils'

export const HEATMAP_PRESET_WIDTHS = [320, 375, 425, 768, 1024, 1440, 1920]

export interface HeatmapCoverageRow {
    type: HeatmapKind
    width: number
    count: number
}

export interface HeatmapUrlDiagnosis {
    sameUrlAnyDateCount: number
    pageAnyQueryCount: number
    similarUrls: { url: string; count: number }[]
}

export type HeatmapEmptyDiagnosis =
    | { reason: 'capture_off' }
    | { reason: 'other_widths'; width: number; share: number }
    | { reason: 'other_types'; type: HeatmapKind; count: number }
    | { reason: 'other_dates'; count: number }
    | { reason: 'other_query_strings'; count: number }
    | { reason: 'similar_urls'; urls: { url: string; count: number }[] }
    | { reason: 'other_filters' }
    | { reason: 'no_data' }

export const computeWidthShares = (
    rows: HeatmapCoverageRow[],
    type: HeatmapKind,
    heatmapFilters: HeatmapFilters,
    widths: number[]
): Record<number, number> => {
    const typeRows = rows.filter((row) => row.type === type)
    const total = typeRows.reduce((sum, row) => sum + row.count, 0)
    const shares: Record<number, number> = {}
    for (const width of widths) {
        const { min, max } = calculateViewportRange(heatmapFilters, width)
        const inBand = typeRows.reduce((sum, row) => (row.width >= min && row.width <= max ? sum + row.count : sum), 0)
        shares[width] = total > 0 ? inBand / total : 0
    }
    return shares
}

export const diagnoseEmptyHeatmap = ({
    captureEnabled,
    rows,
    type,
    heatmapFilters,
    analysisWidth,
    urlDiagnosis,
}: {
    captureEnabled: boolean
    rows: HeatmapCoverageRow[]
    type: HeatmapKind
    heatmapFilters: HeatmapFilters
    analysisWidth: number
    urlDiagnosis: HeatmapUrlDiagnosis | null
}): HeatmapEmptyDiagnosis => {
    if (!captureEnabled) {
        return { reason: 'capture_off' }
    }
    const widths = Array.from(new Set([...HEATMAP_PRESET_WIDTHS, analysisWidth]))
    const shares = computeWidthShares(rows, type, heatmapFilters, widths)
    if ((shares[analysisWidth] ?? 0) > 0) {
        return { reason: 'other_filters' }
    }
    const [bestWidth, bestShare] = HEATMAP_PRESET_WIDTHS.map((width): [number, number] => [width, shares[width]]).sort(
        (a, b) => b[1] - a[1]
    )[0]
    if (bestShare > 0) {
        return { reason: 'other_widths', width: bestWidth, share: bestShare }
    }
    const countsByType = new Map<HeatmapKind, number>()
    for (const row of rows) {
        if (row.type !== type) {
            countsByType.set(row.type, (countsByType.get(row.type) ?? 0) + row.count)
        }
    }
    const [otherType, otherCount] = Array.from(countsByType.entries()).sort((a, b) => b[1] - a[1])[0] ?? [null, 0]
    if (otherType && otherCount > 0) {
        return { reason: 'other_types', type: otherType, count: otherCount }
    }
    if (!urlDiagnosis) {
        return { reason: 'no_data' }
    }
    if (urlDiagnosis.sameUrlAnyDateCount > 0) {
        return { reason: 'other_dates', count: urlDiagnosis.sameUrlAnyDateCount }
    }
    if (urlDiagnosis.pageAnyQueryCount > 0) {
        return { reason: 'other_query_strings', count: urlDiagnosis.pageAnyQueryCount }
    }
    if (urlDiagnosis.similarUrls.length > 0) {
        return { reason: 'similar_urls', urls: urlDiagnosis.similarUrls }
    }
    return { reason: 'no_data' }
}
