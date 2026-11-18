import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel, subscribeToTicker } from 'lib/components/TZLabel'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
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
    const { isVisible } = usePageVisibility()
    const [, refresh] = useState(0)
    const now = Date.now()
    const next = nextRunAt(config, currentTeam?.timezone ?? 'UTC', new Date(now))
    const dueAt = next?.getTime() ?? null
    const isDue = dueAt !== null && dueAt <= now

    // Surfaces that don't poll never re-render this, so it flips itself to "Due now".
    useEffect(() => {
        if (dueAt === null || isDue || !isVisible) {
            return
        }
        return subscribeToTicker(() => {
            if (dueAt <= Date.now()) {
                refresh((count) => count + 1)
            }
        })
    }, [dueAt, isDue, isVisible])

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
