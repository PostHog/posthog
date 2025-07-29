import { useValues } from 'kea'
import { useMemo } from 'react'

import { DateRange, ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { SparklineData } from '../components/SparklineChart/SparklineChart'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { ERROR_TRACKING_DETAILS_RESOLUTION } from '../utils'

type NotUndefined<T> = T extends undefined ? never : T

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
    dateRange: DateRange,
    volumeResolution: number
): SparklineData {
    return useMemo(() => {
        if (aggregations?.volume_buckets) {
            return generateDataFromVolumeBuckets(aggregations.volume_buckets)
        }
        return new Array(volumeResolution).fill({ value: 0, date: new Date() })
    }, [aggregations, dateRange, volumeResolution])
}

export function useSparklineDataIssueScene(): SparklineData {
    const { aggregations, dateRange } = useValues(errorTrackingIssueSceneLogic)
    return useSparklineData(aggregations, dateRange, ERROR_TRACKING_DETAILS_RESOLUTION)
}
