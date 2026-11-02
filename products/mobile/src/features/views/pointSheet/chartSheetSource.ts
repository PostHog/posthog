import type { QueryKey } from '@tanstack/react-query'

import type { InsightSnapshot } from '@/model/views'

import { useSnapshot } from '../viewsCache'

/** The chart a Point sheet or an About sheet describes. */
export interface ChartSheetSource {
    /** The snapshot when the sheet opened. */
    snapshot: InsightSnapshot
    /** The snapshot's cache entry. While the sheet is open it follows this entry, so a refresh shows at once. */
    queryKey: QueryKey | null
    /** The snapshot's freshness key, for the About sheet's Refresh. */
    itemKey: string | null
    /** The screen's `refresh.refreshItem`. Without it the About sheet has no Refresh. */
    refreshItem?: (itemKey: string) => boolean
    /** The dashboard the chart sits on, for the About sheet's Source section. */
    dashboardName?: string | null
}

/** The source's snapshot as the cache holds it now. */
export function useLiveSnapshot(source: ChartSheetSource | null): InsightSnapshot | undefined {
    const live = useSnapshot<InsightSnapshot>(source?.queryKey ?? null)
    return live ?? source?.snapshot
}
