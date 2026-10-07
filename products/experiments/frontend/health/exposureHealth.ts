import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

const SAMPLE_RATIO_MISMATCH_P_VALUE = 0.001

export function hasSampleRatioMismatch(exposures: ExperimentExposureQueryResponse | null | undefined): boolean {
    return (
        exposures?.sample_ratio_mismatch != null &&
        exposures.sample_ratio_mismatch.p_value < SAMPLE_RATIO_MISMATCH_P_VALUE
    )
}

/** The exposed users of every variant in the exposure answer, the `$multiple` variant included. */
export function getTotalExposures(exposures: ExperimentExposureQueryResponse | null | undefined): number {
    return (exposures?.timeseries ?? []).reduce(
        (total, series) => total + Number(exposures?.total_exposures?.[series.variant] || 0),
        0
    )
}
