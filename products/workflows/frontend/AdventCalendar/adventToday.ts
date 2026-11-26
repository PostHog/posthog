import { ADVENT_LAST_DAY, ADVENT_YEAR } from './adventContent'

export interface AdventDayOverride {
    requestedDay: string | null
    canPickDay: boolean
}

function clampDay(day: number): number {
    return Math.max(0, Math.min(ADVENT_LAST_DAY, Math.floor(day)))
}

function dayOfDate(now: Date): number {
    if (now.getFullYear() < ADVENT_YEAR || (now.getFullYear() === ADVENT_YEAR && now.getMonth() < 11)) {
        return 0
    }
    if (now.getFullYear() > ADVENT_YEAR) {
        return ADVENT_LAST_DAY
    }
    return clampDay(now.getDate())
}

export function adventToday(now: Date, { requestedDay, canPickDay }: AdventDayOverride): number {
    const day = canPickDay && requestedDay?.trim() ? Number(requestedDay) : NaN
    return Number.isFinite(day) ? clampDay(day) : dayOfDate(now)
}
