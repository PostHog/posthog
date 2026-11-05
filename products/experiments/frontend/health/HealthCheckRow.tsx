import { useActions } from 'kea'
import { useId, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { HealthCheckPlainRow } from './HealthCheckPlainRow'
import { type ListedHealthCheck, healthMeasurementText } from './healthPanelChecks'

export function HealthCheckRow({ check, icon }: { check: ListedHealthCheck; icon: JSX.Element }): JSX.Element {
    const [isDetailOpen, setIsDetailOpen] = useState(false)
    const detailId = useId()
    const { reportHealthCheckExpanded } = useActions(experimentLogic)
    const name = <span className={cn(check.status === 'not_applicable' && 'text-secondary')}>{check.name}</span>

    if (!check.description) {
        // An exposure answer cached before the descriptions existed has nothing to show.
        return <HealthCheckPlainRow icon={icon}>{name}</HealthCheckPlainRow>
    }

    return (
        <li className="flex flex-col">
            <LemonButton
                size="xsmall"
                icon={icon}
                className="-mx-1"
                onClick={() => {
                    if (!isDetailOpen) {
                        reportHealthCheckExpanded(check)
                    }
                    setIsDetailOpen(!isDetailOpen)
                }}
                aria-expanded={isDetailOpen}
                aria-controls={detailId}
                data-attr="experiment-health-check"
            >
                {name}
            </LemonButton>
            {isDetailOpen && (
                <div id={detailId} className="flex flex-col gap-1 pl-5 pb-1 text-xs">
                    <p className="m-0 text-secondary">{check.description}</p>
                    {check.measurement && <span>{healthMeasurementText(check.measurement)}</span>}
                </div>
            )}
        </li>
    )
}
