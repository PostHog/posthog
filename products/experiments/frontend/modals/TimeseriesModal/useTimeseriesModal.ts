import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { dayjs } from 'lib/dayjs'
import { type ProcessedChartData, experimentTimeseriesLogic } from 'scenes/experiments/experimentTimeseriesLogic'
import { ExperimentVariantResult } from 'scenes/experiments/MetricsView/shared/utils'

import { ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { EXPERIMENT_RECALCULATION_MAX_AGE_DAYS } from 'products/experiments/frontend/constants'
import { hasEnded, isLaunched } from 'products/experiments/frontend/experimentStatus'

export const TIMESERIES_RECALCULATE_TITLE = 'Recalculate timeseries data'
export const TIMESERIES_RECALCULATE_WARNING =
    'All existing timeseries data will be deleted and recalculated from scratch. This could take a long time for large datasets.'
export const TIMESERIES_STALE_NOTE = `This experiment has been running for more than ${EXPERIMENT_RECALCULATION_MAX_AGE_DAYS} days. Automatic timeseries updates are disabled. You can still manually recalculate the data.`
export const TIMESERIES_PROGRESS_HELP =
    'The chart displays data starting from the first day with meaningful results. Earlier days without sufficient data are excluded from the visualization.'

export interface TimeseriesModalModel {
    chartData: ProcessedChartData | null
    progressMessage: string | null
    hasTimeseriesData: boolean
    timeseriesLoading: boolean
    isRecalculating: boolean
    recalculationCreatedAt: string | null | undefined
    isStaleExperiment: boolean
    recalculate: () => void
    refresh: () => void
}

export function useTimeseriesModal({
    isOpen,
    metric,
    variantResult,
    experiment,
}: {
    isOpen: boolean
    metric: ExperimentMetric
    variantResult: ExperimentVariantResult
    experiment: Experiment
}): TimeseriesModalModel {
    const logic = experimentTimeseriesLogic({ experiment, metric: isOpen ? metric : undefined })
    const { chartData, progressMessage, hasTimeseriesData, timeseriesLoading, isRecalculating, timeseries } =
        useValues(logic)
    const { recalculateTimeseries, loadTimeseries } = useActions(logic)

    const processedChartData = useMemo(() => {
        return chartData(variantResult.key)
    }, [chartData, variantResult.key])

    return {
        chartData: processedChartData,
        progressMessage,
        hasTimeseriesData,
        timeseriesLoading,
        isRecalculating,
        recalculationCreatedAt: timeseries?.recalculation_created_at,
        isStaleExperiment:
            isLaunched(experiment) && !hasEnded(experiment)
                ? dayjs(experiment.start_date).isBefore(dayjs().subtract(EXPERIMENT_RECALCULATION_MAX_AGE_DAYS, 'days'))
                : false,
        recalculate: () => recalculateTimeseries({ metric }),
        refresh: () => loadTimeseries({ metric }),
    }
}
