import type { ExperimentExposureHealthFinding, ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

const SAMPLE_RATIO_MISMATCH_P_VALUE = 0.001

export const SAMPLE_RATIO_MISMATCH_DESCRIPTION =
    "The distribution of users across variants doesn't match your configured rollout percentages (p < 0.001). This may indicate issues with randomization or data collection."

export function hasSampleRatioMismatch(exposures: ExperimentExposureQueryResponse | null | undefined): boolean {
    return (
        exposures?.sample_ratio_mismatch != null &&
        exposures.sample_ratio_mismatch.p_value < SAMPLE_RATIO_MISMATCH_P_VALUE
    )
}

export const SAMPLE_RATIO_MATCH_DESCRIPTION =
    'No sample ratio mismatch detected. The difference between actual and expected exposures is within normal random variation.'

/** The server's sample ratio finding in the exposure answer, or undefined when the server reports none. */
export function serverSampleRatioFinding(
    exposures: ExperimentExposureQueryResponse | null | undefined
): ExperimentExposureHealthFinding | undefined {
    return exposures?.health_findings?.find(({ code }) => code === 'srm')
}

/** What the exposures card says about the sample ratio test. */
export type SampleRatioLine = {
    tone: 'warning' | 'info' | 'success'
    label: string
    tooltip: string
}

/** Whether the exposures card's line reports a mismatch, as a warning or as info. */
export function reportsMismatch(line: SampleRatioLine | null): line is SampleRatioLine & { tone: 'warning' | 'info' } {
    return line !== null && line.tone !== 'success'
}

/**
 * The exposures card's line about the sample ratio test, or null without a test. With the health panel the card uses
 * the server's finding, which can name a split change as the likely cause. Without it the card keeps the page's own
 * rule and text.
 */
export function sampleRatioLine(
    exposures: ExperimentExposureQueryResponse | null | undefined,
    followsServer: boolean
): SampleRatioLine | null {
    if (exposures?.sample_ratio_mismatch == null) {
        return null
    }
    // SRM doesn't apply when every release condition sets a variant override. The override finding explains it.
    if (
        followsServer &&
        exposures.health_checks?.some(({ key, status }) => key === 'srm' && status === 'not_applicable')
    ) {
        return null
    }
    const finding = followsServer ? serverSampleRatioFinding(exposures) : undefined
    if (finding) {
        return {
            tone: finding.severity === 'info' ? 'info' : 'warning',
            label:
                finding.subcode === 'split_changed'
                    ? 'Sample ratio mismatch after a split change'
                    : 'Sample ratio mismatch detected',
            tooltip: finding.detail,
        }
    }
    return hasSampleRatioMismatch(exposures)
        ? { tone: 'warning', label: 'Sample ratio mismatch detected', tooltip: SAMPLE_RATIO_MISMATCH_DESCRIPTION }
        : {
              tone: 'success',
              label: 'Exposure distribution matches rollout percentages',
              tooltip: SAMPLE_RATIO_MATCH_DESCRIPTION,
          }
}

/** The exposed users of every variant in the exposure answer, the `$multiple` variant included. */
export function getTotalExposures(exposures: ExperimentExposureQueryResponse | null | undefined): number {
    return (exposures?.timeseries ?? []).reduce(
        (total, series) => total + Number(exposures?.total_exposures?.[series.variant] || 0),
        0
    )
}
