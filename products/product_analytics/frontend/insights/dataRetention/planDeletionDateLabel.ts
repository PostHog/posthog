import { dayjs } from 'lib/dayjs'

import type { EventsRetentionApi } from 'products/product_analytics/frontend/generated/api.schemas'

function dateLabel(date: string | null | undefined): string | null {
    return date ? dayjs(date).format('MMMM D, YYYY') : null
}

export function planDeletionDateLabel(retention: EventsRetentionApi | null): string | null {
    return dateLabel(retention?.next_deletion_on)
}

export function deletionCutoffLabel(retention: EventsRetentionApi | null): string | null {
    return dateLabel(retention?.next_deletion_before)
}
