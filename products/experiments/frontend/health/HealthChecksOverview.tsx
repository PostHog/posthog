import { LemonTag } from '@posthog/lemon-ui'

import { HealthCheckList } from './HealthCheckList'
import { HealthChecksSummary } from './HealthChecksSummary'
import { HealthFindingRow } from './HealthFindingRow'
import { type HealthPanelCheck, listedHealthChecks } from './healthPanelChecks'
import type { HealthPanelFinding } from './healthPanelFindings'

export function HealthChecksOverview({
    checks,
    notes,
    isDraft,
    exposureChecksMissing,
}: {
    checks: HealthPanelCheck[]
    notes: HealthPanelFinding[]
    isDraft: boolean
    exposureChecksMissing: boolean
}): JSX.Element {
    const listedChecks = listedHealthChecks(checks)

    return (
        <div className="flex flex-col w-96 max-w-full" data-attr="experiment-health-overview">
            <div className="flex flex-col gap-1 px-3 py-2">
                <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">Health checks</span>
                    <LemonTag type="completion">Beta</LemonTag>
                </div>
                <HealthChecksSummary checks={checks} isDraft={isDraft} />
            </div>
            {notes.length > 0 && (
                // A note mounts, and so reports as shown, only when the reader opens this overview.
                <div className="divide-y border-t">
                    {notes.map((finding) => (
                        <HealthFindingRow key={`${finding.code}:${finding.subcode ?? ''}`} finding={finding} />
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
