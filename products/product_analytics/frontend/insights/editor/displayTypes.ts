import { isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

// Their own module so an option component can read these groupings without importing the
// DisplayOptions registry that renders it.
export const LINE_DISPLAYS = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsLineGraphCumulative,
    ChartDisplayType.ActionsAreaGraph,
] as const
export const BAR_DISPLAYS = [
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsUnstackedBar,
    ChartDisplayType.ActionsBarValue,
] as const

export function displayMatches(
    display: ChartDisplayType | null | undefined,
    displays: readonly ChartDisplayType[]
): boolean {
    return !!display && displays.includes(display)
}

export function isDefaultTrendsLineDisplay(
    display: ChartDisplayType | null | undefined,
    querySource: Parameters<typeof isTrendsQuery>[0]
): boolean {
    return !display && isTrendsQuery(querySource)
}
