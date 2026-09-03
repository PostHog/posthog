import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
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
    const now = new Date()
    const next = nextRunAt(config, currentTeam?.timezone ?? 'UTC', now)

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
