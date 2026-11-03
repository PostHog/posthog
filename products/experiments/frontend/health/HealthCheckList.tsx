import { IconCheck, IconMinus, IconQuestion } from '@posthog/icons'

import { HealthCheckRow } from './HealthCheckRow'
import type { ListedHealthCheck } from './healthPanelChecks'

type ListedStatus = ListedHealthCheck['status']

const STATUS_DISPLAY: Record<ListedStatus, { icon: JSX.Element; label: string }> = {
    not_checked: { icon: <IconQuestion className="text-secondary" />, label: "Couldn't check" },
    passed: { icon: <IconCheck className="text-success" />, label: 'No issue found' },
    not_applicable: { icon: <IconMinus className="text-tertiary" />, label: "Doesn't apply" },
}

interface CheckGroup {
    label: string
    status: ListedStatus
    checks: ListedHealthCheck[]
}

// Checks that share an outcome share a heading, so a reason such as "Runs after launch" shows once.
function groupByOutcome(checks: ListedHealthCheck[]): CheckGroup[] {
    const groups = new Map<string, CheckGroup>()
    for (const check of checks) {
        const label = check.reason ?? STATUS_DISPLAY[check.status].label
        const key = `${check.status}:${label}`
        const group = groups.get(key) ?? { label, status: check.status, checks: [] }
        group.checks.push(check)
        groups.set(key, group)
    }
    return [...groups.values()]
}

export function HealthCheckList({
    checks,
    exposureChecksMissing,
}: {
    checks: ListedHealthCheck[]
    exposureChecksMissing: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-4 px-3 py-2" data-attr="experiment-health-check-list">
            {exposureChecksMissing && (
                // The exposure checks come with the exposure answer, so without one the page has no names for them.
                <div className="flex flex-col gap-1">
                    <span className="text-xs font-semibold text-secondary">
                        Couldn't check. Refresh the results to run these checks.
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="flex shrink-0 text-base">{STATUS_DISPLAY.not_checked.icon}</span>
                        <span>Exposure checks</span>
                    </span>
                </div>
            )}
            {groupByOutcome(checks).map((group) => (
                <div key={`${group.status}:${group.label}`} className="flex flex-col gap-1">
                    <span className="text-xs font-semibold text-secondary">{group.label}</span>
                    <ul className="m-0 p-0 list-none flex flex-col">
                        {group.checks.map((check) => (
                            <HealthCheckRow key={check.key} check={check} icon={STATUS_DISPLAY[group.status].icon} />
                        ))}
                    </ul>
                </div>
            ))}
        </div>
    )
}
