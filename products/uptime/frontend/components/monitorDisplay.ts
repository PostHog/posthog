import { dayjs } from 'lib/dayjs'

import type { MonitorSummaryDTOApi } from '../generated/api.schemas'

export type MonitorStatus = MonitorSummaryDTOApi['status']

export function monitorStatusDotVariant(status: MonitorStatus): 'success' | 'destructive' | 'default' {
    switch (status) {
        case 'up':
            return 'success'
        case 'down':
            return 'destructive'
        default:
            return 'default'
    }
}

export function monitorStatusLabel(status: MonitorStatus): string {
    switch (status) {
        case 'up':
            return 'Operational'
        case 'down':
            return 'Down'
        default:
            return 'Awaiting data'
    }
}

export function formatPercent(value: number): string {
    if (value >= 1) {
        return '100%'
    }
    return `${(value * 100).toFixed(2)}%`
}

export function formatDuration(start: dayjs.Dayjs, end: dayjs.Dayjs): string {
    const seconds = Math.max(1, end.diff(start, 'second'))
    if (seconds < 60) {
        return `${seconds}s`
    }
    const minutes = Math.floor(seconds / 60)
    const remainder = seconds % 60
    if (minutes < 60) {
        return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`
    }
    const hours = Math.floor(minutes / 60)
    const rmin = minutes % 60
    if (hours < 24) {
        return rmin ? `${hours}h ${rmin}m` : `${hours}h`
    }
    const days = Math.floor(hours / 24)
    const rhr = hours % 24
    return rhr ? `${days}d ${rhr}h` : `${days}d`
}
