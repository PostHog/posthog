import { ADVENT_YEAR } from './adventContent'

const MINUTE_MS = 60_000

export function adventOpenedOnItsDay(day: number, openedAt: Date, utcOffsetMinutes: number): boolean {
    const local = new Date(openedAt.getTime() + utcOffsetMinutes * MINUTE_MS)
    return local.getUTCFullYear() === ADVENT_YEAR && local.getUTCMonth() === 11 && local.getUTCDate() === day
}

export function adventTicketsLabel(count: number): string {
    return count === 1 ? '1 ticket' : `${count} tickets`
}
