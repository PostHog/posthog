import { HealthFindingActionButton } from './HealthFindingActionButton'
import { HealthFindingSeverityIcon } from './HealthFindingSeverityIcon'
import { HEALTH_FINDING_SEVERITY_LABELS, type HealthPanelFinding } from './healthPanelFindings'
import { useHealthFindingReporting } from './useHealthFindingReporting'

export function HealthFindingDetail({
    finding,
    onActedOn,
}: {
    finding: HealthPanelFinding
    onActedOn?: () => void
}): JSX.Element {
    const { reportActedOn } = useHealthFindingReporting({
        code: finding.code,
        subcode: finding.subcode ?? undefined,
        severity: finding.severity,
        reason: finding.reason ?? undefined,
    })

    return (
        <div className="flex flex-col gap-3" data-attr="experiment-health-finding-detail">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex flex-col gap-1 min-w-0">
                    <h3 className="m-0 flex items-center gap-2 text-base font-semibold">
                        <HealthFindingSeverityIcon severity={finding.severity} />
                        <span>{finding.title}</span>
                    </h3>
                    <span className="pl-6 text-xs text-secondary">
                        {HEALTH_FINDING_SEVERITY_LABELS[finding.severity]}
                    </span>
                </div>
                {finding.actions.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2">
                        {finding.actions.map((actionKind) => (
                            <HealthFindingActionButton
                                key={actionKind}
                                actionKind={actionKind}
                                onClick={() => {
                                    reportActedOn(actionKind)
                                    onActedOn?.()
                                }}
                            />
                        ))}
                    </div>
                )}
            </div>
            <p className="m-0 max-w-prose text-secondary whitespace-pre-line">{finding.detail}</p>
        </div>
    )
}
