import type { ResultSeries } from 'scenes/insights/utils/resultSeries'

import { getResultSeriesName } from './resultSeriesName'

export type SeriesIdentification = 'none' | 'name' | 'letter-and-name'

interface SeriesIdentity {
    series?: ResultSeries
    order?: number
    series_name?: string
}

export function getSeriesIdentification(series: Iterable<SeriesIdentity>): SeriesIdentification {
    const nameByEntity = new Map<number | string, string>()
    for (const item of series) {
        if (item.series?.node) {
            nameByEntity.set(item.series.order, getResultSeriesName(item.series) ?? '')
        } else if (item.series_name != null && item.order != null) {
            nameByEntity.set(item.order, item.series_name)
        }
    }
    if (nameByEntity.size <= 1) {
        return 'none'
    }
    return new Set(nameByEntity.values()).size < nameByEntity.size ? 'letter-and-name' : 'name'
}
