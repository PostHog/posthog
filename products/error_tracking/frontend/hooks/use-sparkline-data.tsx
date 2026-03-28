import { useValues } from 'kea'
import { useMemo } from 'react'

import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'
import { dateStringToDayJs } from 'lib/utils'

import { DateRange, ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import type { SparklineData } from '../components/VolumeSparkline/types'
import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { ERROR_TRACKING_DETAILS_RESOLUTION } from '../utils'

type NotUndefined<T> = T extends undefined ? never : T

function generateFallbackData(dateRange: DateRange | undefined, volumeResolution: number): SparklineData {
    const defaultData = new Array(volumeResolution).fill({ value: 0, date: new Date() })

    if (!dateRange || !dateRange.date_from) {
        return defaultData
    }

    const dateFrom = dateStringToDayJs(dateRange.date_from)
    const dateTo = dateStringToDayJs(dateRange.date_to ?? new Date().toISOString())

    if (!dateFrom || !dateTo) {
        return defaultData
    }

    const totalMs = dateTo.diff(dateFrom, 'ms')

    const binSize = totalMs / volumeResolution

    if (binSize === 0) {
        return defaultData
    }

    return defaultData.map(({ value }, index) => ({
        value,
        date: dateFrom.add(index * binSize, 'ms').toDate(),
    }))
}

function generateDataFromVolumeBuckets(
    volumeBuckets: NotUndefined<ErrorTrackingIssueAggregations['volume_buckets']>
): SparklineData {
    return volumeBuckets.map(({ label, value }) => ({
        value,
        date: new Date(label),
    }))
}

export function useSparklineData(
    aggregations: ErrorTrackingIssueAggregations | undefined,
    volumeResolution: number,
    dateRange?: DateRange
): SparklineData {
    return useMemo(() => {
        if (aggregations?.volume_buckets) {
            return generateDataFromVolumeBuckets(aggregations.volume_buckets)
        }

        return generateFallbackData(dateRange, volumeResolution)
    }, [aggregations, volumeResolution, dateRange])
}

export function useSparklineDataIssueScene(): SparklineData {
    const { aggregations, dateRange, spikeEvents } = useValues(errorTrackingIssueSceneLogic)
    const data = useSparklineData(aggregations, ERROR_TRACKING_DETAILS_RESOLUTION, dateRange)
    return useMemo(() => applyVolumeSpikeHighlights(data, spikeEvents), [data, spikeEvents])
}

export function applyVolumeSpikeHighlights(
    data: SparklineData,
    spikeEvents: ErrorTrackingSpikeEvent[],
    spikeStripeColor = 'var(--brand-yellow)'
): SparklineData {
    if (spikeEvents.length === 0 || data.length < 2) {
        return data
    }

    const binSizeMs = data[1].date.getTime() - data[0].date.getTime()
    const spikeTimestamps = spikeEvents.map((s) => new Date(s.detected_at).getTime())

    return data.map((datum) => {
        const datumTime = datum.date.getTime()
        const hasSpikeInBin = spikeTimestamps.some((st) => st >= datumTime && st < datumTime + binSizeMs)
        return hasSpikeInBin ? { ...datum, color: spikeStripeColor, animated: true } : datum
    })
}
