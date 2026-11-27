import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { healthChangedWhileExposed, healthFlagChangeTimes } from './healthCheckRows'
import { HealthDailyExposuresChart } from './HealthDailyExposuresChart'
import { HealthDailyShareChart } from './HealthDailyShareChart'
import type { HealthPanelCheck } from './healthPanelChecks'
import type { HealthPanelFinding } from './healthPanelFindings'

/** The exposures by day behind a finding of an exposure check. Nothing for a finding of another check. */
export function HealthFindingDailyChart({
    finding,
    splitCheck,
    exposures,
    units,
}: {
    finding: HealthPanelFinding
    splitCheck: HealthPanelCheck | undefined
    exposures: ExperimentExposureQueryResponse | null
    units: string
}): JSX.Element | null {
    const splitChangedAt = splitCheck ? healthFlagChangeTimes(splitCheck) : []
    if (finding.check === 'split_changed_mid_run') {
        return <HealthDailyExposuresChart exposures={exposures} splitChangedAt={splitChangedAt} units={units} />
    }
    if (finding.check !== 'srm') {
        return null
    }
    const startedOn = finding.evidence.mismatch_started_on
    const splitChanged = finding.subcode === 'split_changed' || (!!splitCheck && healthChangedWhileExposed(splitCheck))
    return (
        <HealthDailyShareChart
            exposures={exposures}
            startedOn={typeof startedOn === 'string' ? startedOn : null}
            splitChangedAt={splitChangedAt}
            showsPlan={!splitChanged}
            units={units}
        />
    )
}
