import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import {
    RETENTION_FIRST_EVER_OCCURRENCE,
    RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
    RETENTION_RECURRING,
} from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { retentionOptions } from './constants'
import { retentionLogic } from './retentionLogic'

/** Explains why every cohort is empty when the events have property filters, which is
 * usually filter values matching no events, or first-time retention anchoring semantics. */
export function RetentionEmptyResultsBanner(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { insightDataLoading } = useValues(insightVizDataLogic(insightProps))
    const { allCohortsEmpty, hasEntityPropertyFilters, retentionFilter } = useValues(retentionLogic(insightProps))

    if (insightDataLoading || !allCohortsEmpty || !hasEntityPropertyFilters) {
        return null
    }

    const retentionType = retentionFilter?.retentionType ?? RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS
    const firstMatchingLabel = retentionOptions[RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS]
    const firstEverLabel = retentionOptions[RETENTION_FIRST_EVER_OCCURRENCE]
    const recurringLabel = retentionOptions[RETENTION_RECURRING]

    let message: string
    if (retentionType === RETENTION_FIRST_EVER_OCCURRENCE) {
        message =
            `No users match these filters. With "${firstEverLabel}" retention, a user only counts if the very ` +
            `first time they ever performed the event matches your property filters. Users whose first ` +
            `occurrence didn't match are excluded entirely. Switch the retention type to "${firstMatchingLabel}" ` +
            `to count users from when your filters first match, or check that your property values match your data.`
    } else if (retentionType === RETENTION_RECURRING) {
        message =
            'No users match these filters in this date range. Check that your property values match your data, ' +
            'or widen the date range.'
    } else {
        message =
            `No users match these filters. With "${firstMatchingLabel}" retention, users are counted from their ` +
            `first event that matches your property filters. If that first match happened before this date range, ` +
            `they won't appear here. Widen the date range, switch the retention type to "${recurringLabel}" to ` +
            `count every matching event, or check that your property values match your data.`
    }

    return (
        <LemonBanner type="info" className="mb-4">
            {message}
        </LemonBanner>
    )
}
