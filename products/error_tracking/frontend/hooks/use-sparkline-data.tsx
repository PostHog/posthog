import { useValues } from 'kea'
import { useMemo } from 'react'

import { dateStringToDayJs } from 'lib/utils'

import { DateRange, ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { SparklineData } from '../components/SparklineChart/SparklineChart'
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
    const { aggregations, dateRange } = useValues(errorTrackingIssueSceneLogic)
    return useSparklineData(aggregations, ERROR_TRACKING_DETAILS_RESOLUTION, dateRange)
}
