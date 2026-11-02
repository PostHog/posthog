import { LemonTag } from '@posthog/lemon-ui'

import { HealthCheckList } from './HealthCheckList'
import { HealthChecksSummary } from './HealthChecksSummary'
import { HealthFindingRow } from './HealthFindingRow'
import { type HealthPanelCheck, listedHealthChecks } from './healthPanelChecks'
import { type HealthPanelFinding, healthIssues } from './healthPanelFindings'

export function HealthChecksOverview({
    checks,
    findings,
    isDraft,
    exposureChecksMissing,
    onFindingActedOn,
}: {
    checks: HealthPanelCheck[]
    /** Issues first, as `healthPanelFindings` sorts them. */
    findings: HealthPanelFinding[]
    isDraft: boolean
    exposureChecksMissing: boolean
    onFindingActedOn: () => void
}): JSX.Element {
    const listedChecks = listedHealthChecks(checks)

    return (
        <div className="flex flex-col w-96 max-w-full" data-attr="experiment-health-overview">
            <div className="flex flex-col gap-1 px-3 py-2">
                <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">Health checks</span>
                    <LemonTag type="completion">Beta</LemonTag>
                </div>
                <HealthChecksSummary checks={checks} issueCount={healthIssues(findings).length} isDraft={isDraft} />
            </div>
            {findings.length > 0 && (
                // A note mounts, and so reports as shown, only when the reader opens this overview. The panel reports the
                // issues on its own.
                <div className="divide-y border-t">
                    {findings.map((finding) => (
                        <HealthFindingRow
                            key={`${finding.code}:${finding.subcode ?? ''}`}
                            finding={finding}
                            onActedOn={onFindingActedOn}
                        />
                    ))}
                </div>
            )}
            {(listedChecks.length > 0 || exposureChecksMissing) && (
                <div className="border-t">
                    <HealthCheckList checks={listedChecks} exposureChecksMissing={exposureChecksMissing} />
                </div>
            )}
        </div>
    )
}
