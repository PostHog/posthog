import { pluralize } from 'lib/utils/strings'

import { type HealthPanelCheck, countHealthChecks, healthChecksVerdict } from './healthPanelChecks'

export function HealthChecksSummaryDetail({
    checks,
    issueCount,
}: {
    checks: HealthPanelCheck[]
    issueCount: number
}): JSX.Element {
    const passedCount = countHealthChecks(checks, 'passed')
    const notApplicableCount = countHealthChecks(checks, 'not_applicable')
    const text = [
        passedCount > 0 ? `${pluralize(passedCount, 'check')} found no issue.` : null,
        notApplicableCount > 0
            ? `${pluralize(notApplicableCount, 'check')} ${notApplicableCount === 1 ? "doesn't" : "don't"} apply to this experiment.`
            : null,
        'Pick a check to see what it looks for.',
    ]
        .filter(Boolean)
        .join(' ')

    return (
        <div className="flex flex-col gap-1" data-attr="experiment-health-summary-detail">
            <h3 className="m-0 text-base font-semibold">{healthChecksVerdict(checks, issueCount)}</h3>
            <p className="m-0 max-w-prose text-secondary">{text}</p>
        </div>
    )
}
