import { dayjs } from 'lib/dayjs'

import type { EventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'

export function planDeletionDateLabel(retention: EventsRetentionApi | null): string | null {
    return retention?.next_deletion_on ? dayjs(retention.next_deletion_on).format('MMMM D, YYYY') : null
}
