import { IconCheck, IconMinus, IconQuestion } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import type { ListedHealthCheck } from './healthPanelChecks'

type ListedStatus = ListedHealthCheck['status']

const STATUS_DISPLAY: Record<ListedStatus, { icon: JSX.Element; label: string }> = {
    not_checked: { icon: <IconQuestion className="text-secondary" />, label: "Couldn't check" },
    passed: { icon: <IconCheck className="text-success" />, label: 'Looked for, not found' },
    not_applicable: { icon: <IconMinus className="text-tertiary" />, label: "Doesn't apply" },
}

interface CheckGroup {
    label: string
    status: ListedStatus
    rows: { key: string; name: string }[]
}

// Checks that share an outcome share a heading, so a reason such as "Runs after launch" shows once.
function groupByOutcome(checks: ListedHealthCheck[], exposureChecksMissing: boolean): CheckGroup[] {
    const groups = new Map<string, CheckGroup>()
    if (exposureChecksMissing) {
        // The exposure checks come with the exposure answer, so without one the page has no names for them.
        groups.set('exposure_checks_missing', {
            label: "Couldn't check. Refresh the results to run these checks.",
            status: 'not_checked',
            rows: [{ key: 'exposure_checks', name: 'Exposure checks' }],
        })
    }
    for (const check of checks) {
        const label = check.reason ?? STATUS_DISPLAY[check.status].label
        const key = `${check.status}:${label}`
        const group = groups.get(key) ?? { label, status: check.status, rows: [] }
        group.rows.push({ key: check.key, name: check.name })
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
        <div className="flex flex-col gap-2 px-3 py-2" data-attr="experiment-health-check-list">
            {groupByOutcome(checks, exposureChecksMissing).map((group) => (
                <div key={`${group.status}:${group.label}`} className="flex flex-col gap-1">
                    <span className="text-xs font-semibold text-secondary">{group.label}</span>
                    <ul className="m-0 p-0 list-none flex flex-col gap-1">
                        {group.rows.map((row) => (
                            <li key={row.key} className="flex items-center gap-2">
                                <span className="flex shrink-0 text-base">{STATUS_DISPLAY[group.status].icon}</span>
                                <span className={cn(group.status === 'not_applicable' && 'text-secondary')}>
                                    {row.name}
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            ))}
        </div>
    )
}
