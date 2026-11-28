import { ADVENT_LAST_DAY, ADVENT_YEAR } from '../adventContent'
import { adventToday } from '../adventToday'

export type AdventEntryPhase = { status: 'soon' } | { status: 'open'; day: number } | { status: 'over' }

export function adventEntryPhase(now: Date): AdventEntryPhase {
    const day = adventToday(now, { requestedDay: null, canPickDay: false })
    if (day === 0) {
        return { status: 'soon' }
    }
    return now < new Date(ADVENT_YEAR, 11, ADVENT_LAST_DAY + 1) ? { status: 'open', day } : { status: 'over' }
}
