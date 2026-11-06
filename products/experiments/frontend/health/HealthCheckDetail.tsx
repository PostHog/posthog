import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { HealthCheckReadSection } from './HealthCheckReadSection'
import { HealthCheckRuleSection } from './HealthCheckRuleSection'
import { HEALTH_CHECK_STATUS_DISPLAY, healthCheckStatusText } from './healthCheckStatusDisplay'
import type { ListedHealthCheck } from './healthPanelChecks'
import { HealthPanelSection } from './HealthPanelSection'

export function HealthCheckDetail({
    check,
    units,
    exposures,
    checkedAt,
}: {
    check: ListedHealthCheck
    units: string
    exposures: ExperimentExposureQueryResponse | null
    checkedAt: string | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-6" data-attr="experiment-health-check-detail">
            <div className="flex flex-col gap-1">
                <h3 className="m-0 flex items-start gap-2 text-xl font-semibold">
                    <span className="flex shrink-0 pt-1">{HEALTH_CHECK_STATUS_DISPLAY[check.status].icon}</span>
                    <span>{check.name}</span>
                </h3>
                <span className="pl-7 text-xs text-secondary">{healthCheckStatusText(check)}</span>
            </div>
            {check.description && (
                <HealthPanelSection title="What it looks for">
                    <p className="m-0 max-w-prose">{check.description}</p>
                </HealthPanelSection>
            )}
            <HealthCheckReadSection check={check} units={units} exposures={exposures} />
            <HealthCheckRuleSection check={check} units={units} checkedAt={checkedAt} />
        </div>
    )
}
