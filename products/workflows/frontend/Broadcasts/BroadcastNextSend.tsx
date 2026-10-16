import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { HogFlowMinimalApi } from 'products/workflows/frontend/generated/api.schemas'

import { describeRepeat, nextSendTime } from './broadcastNextSend'
import { BroadcastRowDetails } from './broadcastsLogic'

export function BroadcastNextSend({
    broadcast,
    details,
}: {
    broadcast: Pick<HogFlowMinimalApi, 'status'>
    details: BroadcastRowDetails | undefined
}): JSX.Element {
    if (broadcast.status === 'draft' || broadcast.status === 'archived') {
        return <span className="text-muted">-</span>
    }
    if (details?.nextSchedule === undefined) {
        return <span className="text-muted">…</span>
    }
    const schedule = details.nextSchedule
    if (!schedule) {
        return <span className="text-muted">-</span>
    }
    const repeat = describeRepeat(schedule)
    if (schedule.status === 'paused') {
        return (
            <Tooltip title="This schedule paused because its recipients changed. Open the broadcast to schedule it again.">
                <div className="flex flex-col">
                    <span className="text-muted">Paused</span>
                    <span className="text-xs text-muted">{repeat}</span>
                </div>
            </Tooltip>
        )
    }
    const sendTime = nextSendTime(schedule)
    return (
        <div className="flex flex-col">
            {sendTime ? <TZLabel time={sendTime} formatDate="ddd, MMM D" formatTime="h:mm A" /> : null}
            <span className="text-xs text-muted">{repeat}</span>
        </div>
    )
}
