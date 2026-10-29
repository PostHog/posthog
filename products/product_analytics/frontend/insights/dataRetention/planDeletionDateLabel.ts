import { dayjs } from 'lib/dayjs'

import type { EventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'

// The plan's deletion date applies to the hidden events only while the plan's window sets the cutoff. A shorter
// window from settings already deletes those events at every monthly cleanup.
export function planDeletionDateLabel(retention: EventsRetentionApi | null): string | null {
    if (!retention?.next_deletion_on || retention.retention_months !== retention.plan_retention_months) {
        return null
    }
    return dayjs(retention.next_deletion_on).format('MMMM D, YYYY')
}
