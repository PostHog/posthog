import { pluralize } from 'lib/utils/strings'

import { type HealthPanelCheck, countHealthChecks, healthChecksVerdict } from './healthPanelChecks'

export function HealthChecksSummary({
    checks,
    issueCount,
    isDraft,
}: {
    checks: HealthPanelCheck[]
    issueCount: number
    isDraft: boolean
}): JSX.Element {
    const notCheckedCount = countHealthChecks(checks, 'not_checked')

    return (
        // Spans only, because the summary sits inside the button that opens it.
        <span className="flex flex-col gap-0.5" data-attr="experiment-health-summary">
            <span className="font-semibold">{healthChecksVerdict(checks, issueCount)}</span>
            <span className="text-secondary">
                {notCheckedCount > 0 && <span>{pluralize(notCheckedCount, 'check')} couldn't run. </span>}
                {isDraft && <span>More checks run after launch. </span>}
                <span>We're still adding checks, so they don't cover every problem yet.</span>
            </span>
        </span>
    )
}
