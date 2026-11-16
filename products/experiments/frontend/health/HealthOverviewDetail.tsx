import { IconInfo, IconWarning } from '@posthog/icons'

import { pluralize } from 'lib/utils/strings'

import { HEALTH_CHECK_STATUS_DISPLAY } from './healthCheckStatusDisplay'
import { type HealthPanelCheck, countHealthChecks } from './healthPanelChecks'
import { type HealthPanelFinding, healthIssues } from './healthPanelFindings'

export function HealthOverviewDetail({
    checks,
    findings,
}: {
    checks: HealthPanelCheck[]
    findings: HealthPanelFinding[]
}): JSX.Element {
    const issues = healthIssues(findings)
    const issueIcon = (
        <IconWarning
            className={issues.some(({ severity }) => severity === 'critical') ? 'text-danger' : 'text-warning'}
        />
    )
    const noteCount = findings.length - issues.length
    const passedCount = countHealthChecks(checks, 'passed')
    const notApplicableCount = countHealthChecks(checks, 'not_applicable')
    const counts = [
        {
            key: 'issues',
            icon: issueIcon,
            count: issues.length,
            label: pluralize(issues.length, 'issue', undefined, false),
        },
        {
            key: 'notes',
            icon: <IconInfo className="text-secondary" />,
            count: noteCount,
            label: pluralize(noteCount, 'note', undefined, false),
        },
        { key: 'passed', icon: HEALTH_CHECK_STATUS_DISPLAY.passed.icon, count: passedCount, label: 'found no issue' },
        {
            key: 'not_checked',
            icon: HEALTH_CHECK_STATUS_DISPLAY.not_checked.icon,
            count: countHealthChecks(checks, 'not_checked'),
            label: "couldn't check",
        },
        {
            key: 'not_applicable',
            icon: HEALTH_CHECK_STATUS_DISPLAY.not_applicable.icon,
            count: notApplicableCount,
            label: notApplicableCount === 1 ? "doesn't apply" : "don't apply",
        },
    ].filter(({ count }) => count > 0)

    return (
        // pinned: `data-attr` value, so renaming it breaks autocapture insights
        <div className="flex flex-col gap-3" data-attr="experiment-health-summary-detail">
            <h3 className="m-0 text-xl font-semibold">Overview</h3>
            {counts.length > 0 && (
                <ul className="m-0 flex list-none flex-wrap gap-x-6 gap-y-2 p-0">
                    {counts.map(({ key, icon, count, label }) => (
                        <li key={key} className="flex items-center gap-1.5">
                            <span className="flex text-base">{icon}</span>
                            <span className="text-lg font-semibold tabular-nums">{count}</span>
                            <span className="text-secondary">{label}</span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}
