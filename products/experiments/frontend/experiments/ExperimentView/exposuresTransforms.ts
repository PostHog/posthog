import type { Series } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import { ExperimentExposureTimeSeries } from '~/queries/schema/schema-general'

export function buildExposureSeries(timeseries: ExperimentExposureTimeSeries[]): {
    labels: string[]
    series: Series[]
} {
    if (!timeseries.length) {
        return { labels: [], series: [] }
    }

    let labels = timeseries[0].days
    let series: Series[] = timeseries.map((variantTimeseries) => ({
        key: variantTimeseries.variant,
        label: variantTimeseries.variant,
        data: variantTimeseries.exposure_counts,
    }))

    // A single point draws nothing, so give it a zeroed prior day to draw a line from.
    if (labels.length === 1) {
        labels = [dayjs(labels[0]).subtract(1, 'day').format('YYYY-MM-DD'), ...labels]
        series = series.map((variantSeries) => ({ ...variantSeries, data: [0, ...variantSeries.data] }))
    }

    return { labels, series }
}
