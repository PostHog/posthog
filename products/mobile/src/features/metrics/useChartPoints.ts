import { useMemo } from 'react'

import type { MetricData, MetricInterval, MetricSnapshot } from '@/model/types'
import type { ChartPoint } from '@/ui/chart/types'

import { seriesChartPoints, snapshotChartPoints } from './chartPoints'
import { useMetricSeries } from './hooks'

interface ChartPointsFallback {
    snapshot?: MetricSnapshot
    interval: MetricInterval
}

/** `points` is empty when there is nothing to draw. `isLoading` and `isError` describe the live query. */
export interface ChartPointsState {
    points: ChartPoint[]
    isLoading: boolean
    isError: boolean
}

/** The live buckets, else the saved series when one is given. */
export function useChartPoints(data: MetricData | undefined, fallback?: ChartPointsFallback): ChartPointsState {
    const series = useMetricSeries(data)
    const snapshot = fallback?.snapshot
    const interval = fallback?.interval ?? 'day'
    // Memoized so a snapshot measured at an unknown time keeps the same x values between renders.
    const saved = useMemo(
        () => (snapshot ? snapshotChartPoints(snapshot, interval, new Date()) : []),
        [snapshot, interval]
    )
    const live = useMemo(() => (series.data ? seriesChartPoints(series.data) : []), [series.data])
    const state = { isLoading: series.isLoading, isError: series.isError }
    if (live.length > 0) {
        return { points: live, ...state }
    }
    // The chart waits for a live query rather than drawing the saved buckets and then redrawing.
    return { points: series.isLoading ? [] : saved, ...state }
}
