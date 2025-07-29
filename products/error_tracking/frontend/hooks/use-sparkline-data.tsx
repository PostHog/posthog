import { useValues } from 'kea'
import { useMemo } from 'react'

import { DateRange, ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { SparklineData } from '../components/SparklineChart/SparklineChart'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { ERROR_TRACKING_DETAILS_RESOLUTION, generateSparklineLabels } from '../utils'
import { Dayjs } from 'lib/dayjs'

type NotUndefined<T> = T extends undefined ? never : T

function generateDataFromVolumeBuckets(
    volumeBuckets: NotUndefined<ErrorTrackingIssueAggregations['volume_buckets']>
): SparklineData {
    return volumeBuckets.map(({ label, value }) => ({
        value,
        date: new Date(label),
    }))
}

function generateDataFromVolumeRange(
    volumeRange: ErrorTrackingIssueAggregations['volumeRange'],
    labels: Dayjs[]
): SparklineData {
    return volumeRange.map((value, index) => ({
        value,
        date: labels[index].toDate(),
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
        const labels = generateSparklineLabels(dateRange, volumeResolution)
        if (aggregations?.volumeRange) {
            return generateDataFromVolumeRange(aggregations.volumeRange, labels)
        }
        return labels.map((label) => ({
            value: 0,
            date: label.toDate(),
        }))
    }, [aggregations, dateRange, volumeResolution])
}

export function useSparklineDataIssueScene(): SparklineData {
    const { aggregations, dateRange } = useValues(errorTrackingIssueSceneLogic)
    return useSparklineData(aggregations, dateRange, ERROR_TRACKING_DETAILS_RESOLUTION)
}
