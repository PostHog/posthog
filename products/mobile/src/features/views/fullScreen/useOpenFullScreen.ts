import { useRouter } from 'expo-router'
import { useCallback } from 'react'

import { type FullScreenEntry, trackChartFullScreenOpened } from '../analytics'
import type { ChartSheetSource } from '../pointSheet/chartSheetSource'
import { insightDisplay } from '../snapshotChart'
import { chartHref } from '../viewRoutes'

/** Opens a chart full screen on the snapshot it shows now, and sends `mobile_chart_fullscreen_opened`. */
export function useOpenFullScreen(): (source: ChartSheetSource, entry: FullScreenEntry) => void {
    const router = useRouter()
    return useCallback(
        (source: ChartSheetSource, entry: FullScreenEntry) => {
            trackChartFullScreenOpened({ entry, display: insightDisplay(source.snapshot) })
            router.push(chartHref(source.snapshot.shortId, source.queryKey))
        },
        [router]
    )
}
