import { calendarDaysBetween, formatClock, formatMonthDay } from '@/lib/dates'
import type { SnoozeChoice, SnoozePreset } from '@/model/types'

export const SNOOZE_MORNING_HOUR = 9

export const SNOOZE_SIGNAL_COUNT = 5

export type TimePreset = Exclude<SnoozePreset, 'custom'>

function morningIn(days: number, now: Date): Date {
    const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days, SNOOZE_MORNING_HOUR, 0, 0, 0)
    return date
}

export function snoozeUntil(preset: TimePreset, now: Date): Date {
    switch (preset) {
        case 'hour':
            return new Date(now.getTime() + 60 * 60 * 1000)
        case 'tomorrow':
            return morningIn(1, now)
        case 'next_week':
            return morningIn(7, now)
        case 'month':
            return morningIn(30, now)
    }
}

export function formatSnoozeWhen(preset: TimePreset, until: Date): string {
    if (preset === 'hour') {
        return formatClock(until)
    }
    return `${formatMonthDay(until)} at ${formatClock(until)}`
}

export interface SnoozeLabels {
    row: string
    activity: string
}

export function snoozeLabels(choice: SnoozeChoice, now: Date): SnoozeLabels {
    if (choice.kind === 'signals') {
        return { row: 'Snoozed until more signals', activity: `${choice.count} more signals arrive` }
    }
    const until = new Date(choice.until)
    const clock = formatClock(until)
    const days = calendarDaysBetween(now, until)
    if (days <= 0) {
        return { row: `Snoozed until ${clock}`, activity: clock }
    }
    if (days === 1) {
        return { row: 'Snoozed until tomorrow', activity: `tomorrow, ${clock}` }
    }
    const day = formatMonthDay(until)
    return { row: `Snoozed until ${day}`, activity: `${day}, ${clock}` }
}

const CUSTOM_PATTERN = /^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})$/

/** Parses "2026-10-10 09:00" as local time. Returns null for anything else or a time not after `now`. */
export function parseCustomSnooze(input: string, now: Date): Date | null {
    const match = CUSTOM_PATTERN.exec(input.trim())
    if (!match) {
        return null
    }
    const [, year, month, day, hour, minute] = match.map(Number)
    if (year === undefined || month === undefined || day === undefined || hour === undefined || minute === undefined) {
        return null
    }
    const date = new Date(year, month - 1, day, hour, minute, 0, 0)
    const valid =
        date.getFullYear() === year &&
        date.getMonth() === month - 1 &&
        date.getDate() === day &&
        date.getHours() === hour &&
        date.getMinutes() === minute
    if (!valid || date.getTime() <= now.getTime()) {
        return null
    }
    return date
}
