import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

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
    checkedAt,
    onActedOn,
}: {
    finding: HealthPanelFinding
    /** The check that reported the finding. Missing on an exposure answer cached before findings named their check. */
    check: HealthPanelCheck | null
    units: string
    exposures: ExperimentExposureQueryResponse | null
    checkedAt: string | null
    onActedOn?: () => void
}): JSX.Element {
    const { reportActedOn } = useHealthFindingReporting({
        code: finding.code,
        subcode: finding.subcode ?? undefined,
        severity: finding.severity,
        reason: finding.reason ?? undefined,
    })

    return (
        <div className="flex flex-col gap-6" data-attr="experiment-health-finding-detail">
            <h3 className="m-0 flex min-w-0 items-start gap-2 text-xl font-semibold">
                <span className="flex pt-1">
                    <HealthFindingSeverityIcon severity={finding.severity} />
                </span>
                <span>{finding.title}</span>
            </h3>
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
            {check && <HealthCheckRuleSection check={check} units={units} checkedAt={checkedAt} />}
        </div>
    )
}
