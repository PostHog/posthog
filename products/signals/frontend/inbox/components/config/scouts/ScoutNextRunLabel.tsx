import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel, subscribeToTicker } from 'lib/components/TZLabel'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { nextRunAt } from '../../../utils/scoutGroups'

/**
 * When the scout next runs, resolved in the project timezone. A rolling scout whose interval has
 * already elapsed is waiting on the scheduler's next pass, so it reads "Due now" rather than as a
 * time in the past labelled as the future.
 */
export function ScoutNextRunLabel({ config }: { config: SignalScoutConfig }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const [, refresh] = useState(0)
    const now = Date.now()
    const next = nextRunAt(config, currentTeam?.timezone ?? 'UTC', new Date(now))
    const dueAt = next?.getTime() ?? null
    const isDue = dueAt !== null && dueAt <= now

    // A surface that does not poll never re-renders this label on its own, so it would keep showing
    // a time that has passed as the next run. The shared ticker re-renders it as the run falls due.
    useEffect(() => {
        if (dueAt === null || isDue) {
            return
        }
        return subscribeToTicker(() => {
            if (dueAt <= Date.now()) {
                refresh((count) => count + 1)
            }
        })
    }, [dueAt, isDue])

    if (!next) {
        return <span className="text-muted">—</span>
    }
    if (isDue) {
        return (
            <Tooltip title="Past its scheduled time. The scheduler picks it up on its next pass, usually within half an hour.">
                <span>Due now</span>
            </Tooltip>
        )
    }
    return <TZLabel time={next.toISOString()} />
}
