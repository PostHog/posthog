import { DataModelingSyncInterval } from '~/types'

export const INTERVAL_SECONDS: Record<DataModelingSyncInterval, number> = {
    '15min': 15 * 60,
    '30min': 30 * 60,
    '1hour': 60 * 60,
    '6hour': 6 * 60 * 60,
    '12hour': 12 * 60 * 60,
    '24hour': 24 * 60 * 60,
    '7day': 7 * 24 * 60 * 60,
    '30day': 30 * 24 * 60 * 60,
}

export function intervalForSeconds(seconds: number): DataModelingSyncInterval | null {
    const match = Object.entries(INTERVAL_SECONDS).find(([, intervalSeconds]) => intervalSeconds === seconds)
    return match ? (match[0] as DataModelingSyncInterval) : null
}
