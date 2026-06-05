import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import type { IndexedTrendResult } from 'scenes/trends/types'

import type { Noun } from '~/models/groupsModel'
import type { ActionFilter, LifecycleToggle } from '~/types'

export type TrendsSeriesMeta = {
    action?: ActionFilter
    breakdown_value?: string | number | string[]
    compare_label?: SeriesDatum['compare_label']
    days?: string[]
    order?: number
    filter?: SeriesDatum['filter']
}

/** Canonical lifecycle status enumeration: new → resurrecting → returning → dormant.
 *  The lifecycle chart renders series in the reverse order (dormant first) to match the
 *  legacy chart (`trendsDataLogic.ts:197`); see `trendsLifecycleChartTransforms.ts`. */
export const LIFECYCLE_STATUS_ORDER: readonly LifecycleToggle[] = ['new', 'resurrecting', 'returning', 'dormant']

export const buildTrendsSeriesMeta = (r: IndexedTrendResult): TrendsSeriesMeta => ({
    action: r.action,
    breakdown_value: r.breakdown_value,
    compare_label: r.compare_label,
    days: r.days,
    order: r.order ?? r.action?.order ?? 0,
    filter: r.filter,
})

/** Resolve the `groupTypeLabel` shown by tooltips and persons-modal titles.
 *  `'people'` is the default; `'none'` suppresses the noun; anything else
 *  defers to the team's group-type plural. */
export function resolveGroupTypeLabel(
    labelGroupType: 'people' | 'none' | number,
    aggregationLabel: (groupTypeIndex: number | null | undefined) => Noun
): string {
    if (labelGroupType === 'people') {
        return 'people'
    }
    if (labelGroupType === 'none') {
        return ''
    }
    return aggregationLabel(labelGroupType).plural
}
