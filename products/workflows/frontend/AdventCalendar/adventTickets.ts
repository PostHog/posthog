import { ADVENT_LAST_DAY, ADVENT_YEAR } from './adventContent'

const MINUTE_MS = 60_000

export function adventOpenedOnItsDay(day: number, openedAt: Date, utcOffsetMinutes: number): boolean {
    const local = new Date(openedAt.getTime() + utcOffsetMinutes * MINUTE_MS)
    return local.getUTCFullYear() === ADVENT_YEAR && local.getUTCMonth() === 11 && local.getUTCDate() === day
}

export function adventTicketDays(opened: number[], ticketDays: number[]): number[] {
    return [...new Set(ticketDays)].filter((day) => opened.includes(day) && day >= 1 && day <= ADVENT_LAST_DAY)
}

export function adventTicketsLabel(count: number): string {
    return count === 1 ? '1 ticket' : `${count} tickets`
}
