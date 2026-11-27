import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { HealthCheckOutOfDateClock } from './HealthCheckOutOfDateClock'
import { HealthCheckPlainRow } from './HealthCheckPlainRow'
import type { ListedHealthCheck } from './healthPanelChecks'

export function HealthCheckRow({
    check,
    icon,
    isSelected,
    isOutOfDate,
    onSelect,
}: {
    check: ListedHealthCheck
    icon: JSX.Element
    isSelected: boolean
    isOutOfDate: boolean
    onSelect: () => void
}): JSX.Element {
    const name = <span className={cn(check.status === 'not_applicable' && 'text-secondary')}>{check.name}</span>

    if (!check.description) {
        // An exposure answer cached before the descriptions existed has nothing to show.
        return <HealthCheckPlainRow icon={icon}>{name}</HealthCheckPlainRow>
    }

    return (
        <li>
            <LemonButton
                size="xsmall"
                fullWidth
                icon={icon}
                sideIcon={isOutOfDate && check.as_of ? <HealthCheckOutOfDateClock asOf={check.as_of} /> : undefined}
                active={isSelected}
                onClick={onSelect}
                aria-current={isSelected ? 'true' : undefined}
                data-attr="experiment-health-check"
            >
                {name}
            </LemonButton>
        </li>
    )
}
