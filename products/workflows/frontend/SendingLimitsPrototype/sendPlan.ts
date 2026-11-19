// PROTOTYPE (branch prototype/sending-limits-ux): the three answers every variant owes when a broadcast is
// planned: does everyone get it, when does it finish, and why the allowance is what it is. Never merge.
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AllowanceMove, SendingState } from './sendingLimitsPrototypeData'

export interface SendPlan {
    days: { date: string; emails: number }[]
    // "today" or a date such as "Dec 12".
    finish: string
    // The latest change to the allowance, or null when it never changed since the start.
    latestChange: AllowanceMove | null
    // The latest change in one sentence, or null.
    whyChanged: string | null
}

// The prototype's clock is Dec 10, 2026.
function dayLabel(offset: number): string {
    return offset === 0 ? 'Today' : `Dec ${10 + offset}`
}

export function flatPlan(audience: number, perDay: number): SendPlan['days'] {
    const days: SendPlan['days'] = []
    let left = audience
    for (let offset = 0; left > 0 && perDay > 0; offset++) {
        const emails = Math.min(left, perDay)
        days.push({ date: dayLabel(offset), emails })
        left -= emails
    }
    return days
}

// The recipients step plans a new send, so the moved-down state plans at today's lower allowance
// instead of replaying the broadcast that was stopped. D's new sender passes the plan its domain check sets.
export function sendPlan(state: SendingState, days?: SendPlan['days']): SendPlan {
    const planned =
        days ??
        (state.key === 'moved-down'
            ? flatPlan(state.broadcast.audience, state.allowancePerDay)
            : state.broadcast.plan.filter((day) => day.emails > 0))
    const last = planned[planned.length - 1]?.date ?? 'Today'
    const latest = state.moves[state.moves.length - 1]
    const latestChange = latest && latest.direction !== 'start' ? latest : null
    return {
        days: planned,
        finish: last === 'Today' ? 'today' : last,
        latestChange,
        whyChanged: latestChange
            ? `On ${latestChange.date} your allowance went ${latestChange.direction} to ${humanFriendlyNumber(
                  latestChange.to
              )} a day. ${latestChange.reason}`
            : null,
    }
}
