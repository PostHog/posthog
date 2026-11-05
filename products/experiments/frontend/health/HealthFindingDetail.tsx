import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { HealthCheckReadSection } from './HealthCheckReadSection'
import { HealthCheckRuleSection } from './HealthCheckRuleSection'
import { HealthFindingFixes } from './HealthFindingFixes'
import { HealthFindingSeverityIcon } from './HealthFindingSeverityIcon'
import type { HealthPanelCheck } from './healthPanelChecks'
import { HEALTH_FINDING_SEVERITY_LABELS, type HealthPanelFinding } from './healthPanelFindings'
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
    const status = [HEALTH_FINDING_SEVERITY_LABELS[finding.severity], check ? `Found by "${check.name}"` : null]
        .filter(Boolean)
        .join(' · ')

    return (
        <div className="flex flex-col gap-4" data-attr="experiment-health-finding-detail">
            <div className="flex flex-col gap-1 min-w-0">
                <h3 className="m-0 flex items-center gap-2 text-base font-semibold">
                    <HealthFindingSeverityIcon severity={finding.severity} />
                    <span>{finding.title}</span>
                </h3>
                <span className="pl-6 text-xs text-secondary">{status}</span>
            </div>
            <HealthPanelSection title="What we found">
                <p className="m-0 max-w-prose whitespace-pre-line">{finding.detail}</p>
            </HealthPanelSection>
            {check && <HealthCheckReadSection check={check} units={units} exposures={exposures} />}
            {finding.actions.length > 0 && (
                <HealthFindingFixes
                    actions={finding.actions}
                    onActedOn={(actionKind) => {
                        reportActedOn(actionKind)
                        onActedOn?.()
                    }}
                />
            )}
            {check && <HealthCheckRuleSection check={check} units={units} checkedAt={checkedAt} />}
        </div>
    )
}
