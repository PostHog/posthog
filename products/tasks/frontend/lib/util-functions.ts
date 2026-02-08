import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'

export function formatTimeAgo(date: string | Date): string {
    const diff = dayjs().diff(dayjs(date), 'seconds')

    if (diff < 60) {
        return 'just now'
    }

    return `${humanFriendlyDuration(diff, { maxUnits: 1 })} ago`
}
