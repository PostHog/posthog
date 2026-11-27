import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { HealthCheckDataEnd } from './HealthCheckDataEnd'
import { HealthCheckReadSection } from './HealthCheckReadSection'
import { HealthCheckRuleSection } from './HealthCheckRuleSection'
import { HealthFindingFixes } from './HealthFindingFixes'
import { HealthFindingSeverityIcon } from './HealthFindingSeverityIcon'
import type { HealthPanelCheck } from './healthPanelChecks'
import type { HealthPanelFinding } from './healthPanelFindings'
import { HealthPanelSection } from './HealthPanelSection'
import { useHealthFindingReporting } from './useHealthFindingReporting'

export function HealthFindingDetail({
    finding,
    check,
    units,
    exposures,
    isOutOfDate,
    onActedOn,
}: {
    finding: HealthPanelFinding
    /** The check that reported the finding. Missing on an exposure answer cached before findings named their check. */
    check: HealthPanelCheck | null
    units: string
    exposures: ExperimentExposureQueryResponse | null
    isOutOfDate: boolean
    onActedOn?: () => void
}): JSX.Element {
    const { reportActedOn } = useHealthFindingReporting({
        code: finding.code,
        subcode: finding.subcode ?? undefined,
        severity: finding.severity,
        reason: finding.reason ?? undefined,
    })
    const asOf = check?.as_of ?? null

    return (
        <div className="flex flex-col gap-6" data-attr="experiment-health-finding-detail">
            <div className="flex flex-col gap-1">
                <h3 className="m-0 flex min-w-0 items-start gap-2 text-xl font-semibold">
                    <span className="flex pt-1">
                        <HealthFindingSeverityIcon severity={finding.severity} />
                    </span>
                    <span>{finding.title}</span>
                </h3>
                {asOf && (
                    <HealthCheckDataEnd asOf={asOf} isOutOfDate={isOutOfDate} className="pl-7 text-xs text-secondary" />
                )}
            </div>
            <HealthPanelSection title="What we found">
                <p className="m-0 max-w-prose whitespace-pre-line">{finding.detail}</p>
            </HealthPanelSection>
            {finding.actions.length > 0 && (
                <HealthFindingFixes
                    actions={finding.actions}
                    evidence={finding.evidence}
                    onActedOn={(actionKind) => {
                        reportActedOn(actionKind)
                        onActedOn?.()
                    }}
                />
            )}
            {check && <HealthCheckReadSection check={check} units={units} exposures={exposures} />}
            {check && <HealthCheckRuleSection check={check} units={units} />}
        </div>
    )
}
