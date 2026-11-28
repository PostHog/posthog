import { ADVENT_LAST_DAY, ADVENT_YEAR } from './adventContent'

export interface AdventDayOverride {
    requestedDay: string | null
    canPickDay: boolean
}

function clampDay(day: number): number {
    return Math.max(0, Math.min(ADVENT_LAST_DAY, Math.floor(day)))
}

function isBeforeDecember(now: Date): boolean {
    return now.getFullYear() < ADVENT_YEAR || (now.getFullYear() === ADVENT_YEAR && now.getMonth() < 11)
}

function dayOfDate(now: Date): number {
    if (isBeforeDecember(now)) {
        return 0
    }
    if (now.getFullYear() > ADVENT_YEAR) {
        return ADVENT_LAST_DAY
    }
    return clampDay(now.getDate())
}

function pickedDay(now: Date, { requestedDay, canPickDay }: AdventDayOverride): number {
    const mayPick = canPickDay || isBeforeDecember(now)
    return mayPick && requestedDay?.trim() ? Number(requestedDay) : NaN
}

export function adventPicksDay(now: Date, override: AdventDayOverride): boolean {
    return Number.isFinite(pickedDay(now, override))
}

export function adventToday(now: Date, override: AdventDayOverride): number {
    const day = pickedDay(now, override)
    return Number.isFinite(day) ? clampDay(day) : dayOfDate(now)
}
