import { dayjs } from 'lib/dayjs'
import { humanFriendlyCurrency, humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { GoalScoutActivityApi } from 'products/signals/frontend/generated/api.schemas'

export function money(cents: number): string {
    return humanFriendlyCurrency(cents / 100, cents % 100 ? 2 : 0)
}

export function measureValue(value: number | null | undefined, unit = ''): string {
    if (value == null) {
        return '-'
    }
    return `${humanFriendlyNumber(value)}${unit === '%' ? '%' : unit ? ` ${unit}` : ''}`
}

export function difference(value: number, unit: string): string {
    return unit === '%'
        ? `${humanFriendlyNumber(value)} ${value === 1 ? 'point' : 'points'}`
        : measureValue(value, unit)
}

export function delta(start: number, end: number, unit: string): string {
    const change = end - start
    const sign = change > 0 ? '+' : change < 0 ? '−' : ''
    const percent = start ? ` (${sign}${Math.abs(Math.round((change / start) * 100))}%)` : ''
    return `${sign}${difference(Math.abs(change), unit)}${percent}`
}

export function signedPercent(value: number): string {
    const rounded = Math.round(value * 100)
    return `${rounded > 0 ? '+' : rounded < 0 ? '−' : ''}${Math.abs(rounded)}%`
}

export function timeLabels(times: string[]): string[] {
    const sameDay = times.length > 1 && dayjs(times[0]).isSame(dayjs(times[times.length - 1]), 'day')
    return times.map((at) => dayjs(at).format(sameDay ? 'MMM D, HH:mm' : 'MMM D'))
}

export function shortDate(at: string | null): string {
    return at ? dayjs(at).format('MMM D') : ''
}

export function elapsed(start: string, end: string): string {
    const minutes = Math.max(0, dayjs(end).diff(dayjs(start), 'minute'))
    if (minutes < 60) {
        return `${minutes} min`
    }
    if (minutes < 60 * 24) {
        return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
    }
    const days = Math.round(minutes / (60 * 24))
    return `${days} ${days === 1 ? 'day' : 'days'}`
}

export function reachedTarget(value: number | null, target: number | null, direction: string): boolean | null {
    return value !== null && target !== null ? (direction === 'decrease' ? value <= target : value >= target) : null
}

export interface LatestValue {
    value: number
    date: string | null
    stale: boolean
}

export function latestValue(metric: { current: number | null; values: number[]; dates: string[] }): LatestValue | null {
    const date = metric.dates.length ? metric.dates[metric.dates.length - 1] : null
    if (metric.current !== null) {
        return { value: metric.current, date, stale: false }
    }
    return metric.values.length ? { value: metric.values[metric.values.length - 1], date, stale: true } : null
}

export function pullRequestNumber(url: string): string {
    const match = url.match(/\/pull\/(\d+)/)
    return match ? `#${match[1]}` : ''
}

const OWNER_TITLE = /^\s*(?:goal idea:\s*)?owner idea \d+\s*[:.-]\s*/i
const IDEA_TITLE = /^\s*goal idea:\s*/i

export function goalReportTitle(title: string): string {
    if (OWNER_TITLE.test(title)) {
        return `Your idea: ${capitalizeFirstLetter(title.replace(OWNER_TITLE, ''))}`
    }
    return capitalizeFirstLetter(title.replace(IDEA_TITLE, ''))
}

export function errorMessage(error: unknown): string {
    if (typeof error === 'object' && error !== null && 'detail' in error && error.detail) {
        return String(error.detail)
    }
    if (error instanceof Error && error.message) {
        return error.message
    }
    return 'Something went wrong. Try again.'
}

export function activitySubject(detail: string): string {
    return detail.split('. ')[0].replace(/\.$/, '')
}

export function groupActivity(entries: GoalScoutActivityApi[]): GoalScoutActivityApi[][] {
    const groups: GoalScoutActivityApi[][] = []
    for (const entry of entries) {
        const last = groups[groups.length - 1]
        if (last && entry.detail && activitySubject(last[0].detail) === activitySubject(entry.detail)) {
            last.push(entry)
        } else {
            groups.push([entry])
        }
    }
    return groups
}
