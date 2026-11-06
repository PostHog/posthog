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
        <div className="flex flex-col gap-0.5" data-attr="experiment-health-summary">
            <span className="font-semibold">{healthChecksVerdict(checks, issueCount)}</span>
            <p className="m-0 text-secondary">
                {notCheckedCount > 0 && <span>{pluralize(notCheckedCount, 'check')} couldn't run. </span>}
                {isDraft && <span>More checks run after launch. </span>}
                <span>We're still adding checks, so they don't cover every problem yet.</span>
            </p>
        </div>
    )
}
