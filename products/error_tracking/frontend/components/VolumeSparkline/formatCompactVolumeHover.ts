import { dayjs } from 'lib/dayjs'
import { humanFriendlyLargeNumber } from 'lib/utils'

import type { SparklineDatum } from './types'

export function formatCompactVolumeHoverDate(datum: SparklineDatum): string {
    return dayjs(datum.date).utc().format('D MMM HH:mm')
}

export function formatCompactVolumeHoverOccurrences(datum: SparklineDatum): string {
    const formatted = humanFriendlyLargeNumber(datum.value)
    if (datum.value === 1) {
        return `${formatted} occurrence`
    }
    return `${formatted} occurrences`
}
