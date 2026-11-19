import { isCompareSeries } from './chartSeries'
import type { ChartSeries } from './types'

export interface LegendState {
    hiddenKeys: readonly string[]
    /** The series a long press isolated. A tap on it shows every series again. */
    soloKey: string | null
}

export type LegendAction = 'toggle' | 'solo' | 'restore'

export const LEGEND_ALL_VISIBLE: LegendState = { hiddenKeys: [], soloKey: null }

export interface LegendChange {
    state: LegendState
    action: LegendAction
}

function visibleCurrentCount(series: readonly ChartSeries[], hidden: readonly string[]): number {
    return series.filter((s) => !isCompareSeries(s) && !hidden.includes(s.key)).length
}

/** A tap. Returns null when it would hide the last current series, which would leave an empty chart. */
export function toggleSeries(series: readonly ChartSeries[], state: LegendState, key: string): LegendChange | null {
    if (state.soloKey === key) {
        return { state: LEGEND_ALL_VISIBLE, action: 'restore' }
    }
    const hiding = !state.hiddenKeys.includes(key)
    const hiddenKeys = hiding ? [...state.hiddenKeys, key] : state.hiddenKeys.filter((hidden) => hidden !== key)
    if (hiding && visibleCurrentCount(series, hiddenKeys) === 0) {
        return null
    }
    return { state: { hiddenKeys, soloKey: null }, action: 'toggle' }
}

/** A long press shows only this series. On the previous period, which never stands alone, it acts as a tap. */
export function soloSeries(series: readonly ChartSeries[], state: LegendState, key: string): LegendChange | null {
    const target = series.find((s) => s.key === key)
    if (!target || isCompareSeries(target)) {
        return toggleSeries(series, state, key)
    }
    return {
        state: { hiddenKeys: series.filter((s) => s.key !== key).map((s) => s.key), soloKey: key },
        action: 'solo',
    }
}
