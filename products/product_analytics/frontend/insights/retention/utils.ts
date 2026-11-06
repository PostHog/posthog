import { RetentionPeriod } from '~/types'

import { ProcessedRetentionPayload } from './types'

export function formatRetentionCohortLabel(
    cohortRetention: ProcessedRetentionPayload,
    period?: RetentionPeriod
): string {
    if (!cohortRetention.date) {
        return cohortRetention.label
    }

    switch (period) {
        case 'Hour':
            return cohortRetention.date.format('MMM D, h A')
        case 'Month':
            return cohortRetention.date.format('MMM YYYY')
        case 'Week': {
            const startDate = cohortRetention.date
            const endDate = startDate.add(6, 'day')
            return `${startDate.format('MMM D')} to ${endDate.format('MMM D')}`
        }
        default:
            return cohortRetention.date.format('ddd, MMM D')
    }
}
