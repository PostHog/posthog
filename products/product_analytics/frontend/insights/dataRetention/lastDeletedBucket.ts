import { type Dayjs, dayjs } from 'lib/dayjs'

export function lastDeletedBucket(dates: string[], cutoff: Dayjs, timezone: string): number | null {
    const index = dates.findLastIndex((date) => dayjs.tz(date, timezone).isBefore(cutoff))
    return index === -1 ? null : index
}
