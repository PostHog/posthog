import { dayjs } from 'lib/dayjs'

export function lastDeletedBucket(dates: string[], deletesBefore: string): number | null {
    const index = dates.findLastIndex((date) => dayjs(date).isBefore(deletesBefore))
    return index === -1 ? null : index
}
