import { useActions } from 'kea'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { HealthCheckReadSection } from './HealthCheckReadSection'
import { HealthCheckRuleSection } from './HealthCheckRuleSection'
import { HealthFindingFixes } from './HealthFindingFixes'
import { HealthFindingSeverityIcon } from './HealthFindingSeverityIcon'
import type { HealthPanelCheck } from './healthPanelChecks'
import { type HealthPanelFinding, reportedHealthFinding } from './healthPanelFindings'
import { HealthPanelSection } from './HealthPanelSection'
import { useHealthFindingReporting } from './useHealthFindingReporting'

export function HealthFindingDetail({
    finding,
    effects,
    check,
    units,
    exposures,
    checkedAt,
    onActedOn,
}: {
    finding: HealthPanelFinding
    /** The findings that the server says this one causes. Its fixes fix them too, so each shows only the fixes it lacks. */
    effects: HealthPanelFinding[]
    /** The check that reported the finding. Missing on an exposure answer cached before findings named their check. */
    check: HealthPanelCheck | null
    units: string
    exposures: ExperimentExposureQueryResponse | null
    checkedAt: string | null
    onActedOn?: () => void
}): JSX.Element {
    const { reportActedOn } = useHealthFindingReporting(reportedHealthFinding(finding))
    const { reportHealthFindingActedOn } = useActions(experimentLogic)

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
            {effects.length > 0 && (
                <HealthPanelSection title="Also caused by this">
                    <ul className="m-0 flex max-w-prose list-none flex-col gap-4 p-0">
                        {effects.map((effect) => (
                            <li key={`${effect.code}:${effect.subcode ?? ''}`} className="flex flex-col gap-1">
                                <span className="flex items-start gap-2 font-semibold">
                                    <span className="flex pt-0.5">
                                        <HealthFindingSeverityIcon severity={effect.severity} />
                                    </span>
                                    <span>{effect.title}</span>
                                </span>
                                <p className="m-0 whitespace-pre-line">{effect.detail}</p>
                                {/* A cause that offers no such fix, such as a note that only links the flag's history,
                                    must not hide the fix the server gave this finding. */}
                                {effect.actions.some((action) => !finding.actions.includes(action)) && (
                                    <HealthFindingFixes
                                        actions={effect.actions.filter((action) => !finding.actions.includes(action))}
                                        evidence={effect.evidence}
                                        onActedOn={(actionKind) => {
                                            reportHealthFindingActedOn(
                                                reportedHealthFinding(effect, finding),
                                                actionKind
                                            )
                                            onActedOn?.()
                                        }}
                                    />
                                )}
                            </li>
                        ))}
                    </ul>
                </HealthPanelSection>
            )}
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
