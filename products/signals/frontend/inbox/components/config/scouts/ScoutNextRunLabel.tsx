import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { nextRunAt } from '../../../utils/scoutGroups'

/** setTimeout overflows a longer delay and fires at once, so a far-off run waits in stages. */
const MAX_TIMEOUT_MS = 2 ** 31 - 1

/**
 * When the scout next runs, resolved in the project timezone. A rolling scout whose interval has
 * already elapsed is waiting on the scheduler's next pass, so it reads "Due now" rather than as a
 * time in the past labelled as the future.
 */
export function ScoutNextRunLabel({ config }: { config: SignalScoutConfig }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const [, refresh] = useState(0)
    const now = new Date()
    const next = nextRunAt(config, currentTeam?.timezone ?? 'UTC', now)
    const dueAt = next?.getTime() ?? null

    // The label reads the clock only when it renders, and a surface that does not poll can sit for
    // hours without rendering again. Wake it as the run falls due, so a time that has passed stops
    // reading as the future.
    useEffect(() => {
        if (dueAt === null) {
            return
        }
        const delay = dueAt - Date.now()
        if (delay <= 0) {
            return
        }
        const timer = window.setTimeout(() => refresh((count) => count + 1), Math.min(delay, MAX_TIMEOUT_MS))
        return () => window.clearTimeout(timer)
    }, [dueAt])

    if (!next) {
        return <span className="text-muted">—</span>
    }
    if (next.getTime() <= now.getTime()) {
        return (
            <Tooltip title="Past its scheduled time. The scheduler picks it up on its next pass, usually within half an hour.">
                <span>Due now</span>
            </Tooltip>
        )
    }
    return <TZLabel time={next.toISOString()} />
}
