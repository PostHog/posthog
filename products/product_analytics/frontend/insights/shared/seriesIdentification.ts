import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

import type { ActionFilter } from '~/types'

export type SeriesIdentification = 'none' | 'name' | 'letter-and-name'

interface SeriesIdentity {
    action?: ActionFilter | null
    order?: number
    series_name?: string
}

export function getSeriesIdentification(series: Iterable<SeriesIdentity>): SeriesIdentification {
    const nameByEntity = new Map<number | string, string>()
    for (const item of series) {
        if (item.action) {
            const entityKey = item.action.order ?? `${item.action.type}:${item.action.id}`
            nameByEntity.set(entityKey, getDisplayNameFromEntityFilter(item.action) ?? '')
        } else if (item.series_name != null && item.order != null) {
            nameByEntity.set(item.order, item.series_name)
        }
    }
    if (nameByEntity.size <= 1) {
        return 'none'
    }
    return new Set(nameByEntity.values()).size < nameByEntity.size ? 'letter-and-name' : 'name'
}
