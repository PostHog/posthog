import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { healthCheckRowsTable, healthDetectableEffects } from './healthCheckRows'
import { HealthCheckRowsTable } from './HealthCheckRowsTable'
import { type HealthReading, healthCheckReadings, healthExposureSplit } from './healthCheckValues'
import { HealthDailyExposuresChart } from './HealthDailyExposuresChart'
import { HealthDailyShareChart } from './HealthDailyShareChart'
import { HealthDetectableEffectLine } from './HealthDetectableEffectLine'
import { HealthExposureSplitTable } from './HealthExposureSplitTable'
import type { HealthPanelCheck } from './healthPanelChecks'
import type { HealthPanelFinding } from './healthPanelFindings'
import { HealthPanelSection } from './HealthPanelSection'
import { HealthReadingList } from './HealthReadingList'

// These checks compare the variants, so they show the split that the exposure answer counted.
const CHECKS_WITH_SPLIT: ReadonlySet<HealthPanelCheck['key']> = new Set(['srm', 'bias_risk_multiple_excluded'])

export function HealthCheckReadSection({
    check,
    units,
    exposures,
    finding,
}: {
    check: HealthPanelCheck
    units: string
    exposures: ExperimentExposureQueryResponse | null
    /** The finding the check reported. The exposure checks then chart what they read by day. */
    finding?: HealthPanelFinding
}): JSX.Element | null {
    const table = healthCheckRowsTable(check, units)
    // An exposure answer cached before the server added the values keeps the layout without them.
    const hasValues = !!check.values && Object.keys(check.values).length > 0
    if (!hasValues && !table) {
        return null
    }
    const split = CHECKS_WITH_SPLIT.has(check.key) ? healthExposureSplit(exposures) : null
    const countedFrom = split ? exposures?.date_range.date_from : null
    const readings: HealthReading[] = [
        ...healthCheckReadings(check.values, units),
        ...(countedFrom ? [{ label: 'Exposures counted from', time: countedFrom, asDate: true }] : []),
    ]

    const startedOn = finding?.evidence.mismatch_started_on

    return (
        <HealthPanelSection title="What it read">
            {finding && check.key === 'srm' && (
                <HealthDailyShareChart
                    exposures={exposures}
                    startedOn={typeof startedOn === 'string' ? startedOn : null}
                    showsPlan={finding.subcode !== 'split_changed'}
                    units={units}
                />
            )}
            {finding && check.key === 'split_changed_mid_run' && (
                <HealthDailyExposuresChart check={check} exposures={exposures} units={units} />
            )}
            {split && <HealthExposureSplitTable rows={split} units={units} />}
            {readings.length > 0 && <HealthReadingList readings={readings} />}
            {table && <HealthCheckRowsTable table={table} />}
            {healthDetectableEffects(check).map((effect) => (
                <HealthDetectableEffectLine key={effect.variant} effect={effect} />
            ))}
        </HealthPanelSection>
    )
}
