import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { HealthCheckDataEnd } from './HealthCheckDataEnd'
import { HealthCheckReadSection } from './HealthCheckReadSection'
import { HealthCheckRuleSection } from './HealthCheckRuleSection'
import { HEALTH_CHECK_STATUS_DISPLAY, healthCheckStatusText } from './healthCheckStatusDisplay'
import type { ListedHealthCheck } from './healthPanelChecks'
import { HealthPanelSection } from './HealthPanelSection'

export function HealthCheckDetail({
    check,
    units,
    exposures,
    isOutOfDate,
}: {
    check: ListedHealthCheck
    units: string
    exposures: ExperimentExposureQueryResponse | null
    isOutOfDate: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-6" data-attr="experiment-health-check-detail">
            <div className="flex flex-col gap-1">
                <h3 className="m-0 flex items-start gap-2 text-xl font-semibold">
                    <span className="flex shrink-0 pt-1">{HEALTH_CHECK_STATUS_DISPLAY[check.status].icon}</span>
                    <span>{check.name}</span>
                </h3>
                <span className="pl-7 flex flex-wrap items-center gap-1 text-xs text-secondary">
                    <span>{healthCheckStatusText(check)}</span>
                    {/* An exposure answer cached before the server added `as_of` doesn't say how current it is. */}
                    {check.as_of && (
                        <>
                            <span>·</span>
                            <HealthCheckDataEnd asOf={check.as_of} isOutOfDate={isOutOfDate} />
                        </>
                    )}
                </span>
            </div>
            {check.description && (
                <HealthPanelSection title="What it looks for">
                    <p className="m-0 max-w-prose">{check.description}</p>
                </HealthPanelSection>
            )}
            <HealthCheckReadSection check={check} units={units} exposures={exposures} />
            <HealthCheckRuleSection check={check} units={units} />
        </div>
    )
}
