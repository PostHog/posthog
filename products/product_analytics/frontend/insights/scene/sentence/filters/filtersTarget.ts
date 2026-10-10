/** What the editor changes: the filters of the whole insight, or the filters of one event. */
export type FiltersTarget = { kind: 'insight' } | { kind: 'series'; seriesIndex: number }

export const INSIGHT_FILTERS_TARGET: FiltersTarget = { kind: 'insight' }

export function filtersTargetKey(target: FiltersTarget): string {
    return target.kind === 'series' ? `series-${target.seriesIndex}` : 'insight'
}
