import { Spinner } from '@posthog/lemon-ui'

import { HealthCheckPlainRow } from './HealthCheckPlainRow'
import { HealthCheckRow } from './HealthCheckRow'
import { HEALTH_CHECK_STATUS_DISPLAY } from './healthCheckStatusDisplay'
import type { ExposureChecksState, ListedHealthCheck } from './healthPanelChecks'

type ListedStatus = ListedHealthCheck['status']

interface CheckGroup {
    label: string
    status: ListedStatus
    checks: ListedHealthCheck[]
}

// Checks that share an outcome share a heading, so a reason such as "Runs after launch" shows once.
function groupByOutcome(checks: ListedHealthCheck[]): CheckGroup[] {
    const groups = new Map<string, CheckGroup>()
    for (const check of checks) {
        const label = check.reason ?? HEALTH_CHECK_STATUS_DISPLAY[check.status].label
        const key = `${check.status}:${label}`
        const group = groups.get(key) ?? { label, status: check.status, checks: [] }
        group.checks.push(check)
        groups.set(key, group)
    }
    return [...groups.values()]
}

export function HealthCheckList({
    checks,
    checksLoading,
    exposureChecks,
    selectedKey,
    onSelect,
}: {
    checks: ListedHealthCheck[]
    checksLoading: boolean
    exposureChecks: ExposureChecksState
    selectedKey: ListedHealthCheck['key'] | null
    onSelect: (check: ListedHealthCheck) => void
}): JSX.Element | null {
    const running = checksLoading ? 'Health checks' : exposureChecks === 'pending' ? 'Exposure checks' : null
    // While the checks load, the "Health checks" row includes the exposure checks, so a failed exposure answer shows
    // only after the other checks load.
    const exposureChecksMissing = !checksLoading && exposureChecks === 'missing'
    if (!running && !exposureChecksMissing && checks.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-5 border-t px-4 py-3" data-attr="experiment-health-check-list">
            {running && (
                <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold text-secondary">Running</span>
                    <ul className="-mx-2 m-0 p-0 list-none flex flex-col">
                        <HealthCheckPlainRow icon={<Spinner />}>
                            <span>{running}</span>
                        </HealthCheckPlainRow>
                    </ul>
                </div>
            )}
            {exposureChecksMissing && (
                // The exposure checks come with the exposure answer, so without one the page has no names for them.
                <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold text-secondary">
                        Couldn't check. Refresh the results to run these checks.
                    </span>
                    <ul className="-mx-2 m-0 p-0 list-none flex flex-col">
                        <HealthCheckPlainRow icon={HEALTH_CHECK_STATUS_DISPLAY.not_checked.icon}>
                            <span>Exposure checks</span>
                        </HealthCheckPlainRow>
                    </ul>
                </div>
            )}
            {groupByOutcome(checks).map((group) => (
                <div key={`${group.status}:${group.label}`} className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold text-secondary">{group.label}</span>
                    <ul className="-mx-2 m-0 p-0 list-none flex flex-col">
                        {group.checks.map((check) => (
                            <HealthCheckRow
                                key={check.key}
                                check={check}
                                icon={HEALTH_CHECK_STATUS_DISPLAY[group.status].icon}
                                isSelected={check.key === selectedKey}
                                onSelect={() => onSelect(check)}
                            />
                        ))}
                    </ul>
                </div>
            ))}
        </div>
    )
}
