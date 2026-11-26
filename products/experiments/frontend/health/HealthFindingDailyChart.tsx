import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { HealthDailyExposuresChart } from './HealthDailyExposuresChart'
import { HealthDailyShareChart } from './HealthDailyShareChart'
import type { HealthPanelCheck } from './healthPanelChecks'
import type { HealthPanelFinding } from './healthPanelFindings'

/** The exposures by day behind a finding of an exposure check. Nothing for a check without a finding or another check. */
export function HealthFindingDailyChart({
    check,
    finding,
    exposures,
    units,
}: {
    check: HealthPanelCheck
    finding: HealthPanelFinding | undefined
    exposures: ExperimentExposureQueryResponse | null
    units: string
}): JSX.Element | null {
    if (!finding) {
        return null
    }
    if (check.key === 'split_changed_mid_run') {
        return <HealthDailyExposuresChart check={check} exposures={exposures} units={units} />
    }
    if (check.key !== 'srm') {
        return null
    }
    const startedOn = finding.evidence.mismatch_started_on
    return (
        <HealthDailyShareChart
            exposures={exposures}
            startedOn={typeof startedOn === 'string' ? startedOn : null}
            showsPlan={finding.subcode !== 'split_changed'}
            units={units}
        />
    )
}
