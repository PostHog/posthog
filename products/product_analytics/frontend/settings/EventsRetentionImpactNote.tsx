import { Spinner } from 'lib/lemon-ui/Spinner'
import { pluralize } from 'lib/utils/strings'

import type { EventsRetentionImpactApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { retentionPeriodLabel } from './retentionPeriodLabel'

export interface EventsRetentionImpactNoteProps {
    months: number
    impact: EventsRetentionImpactApi | null
    loading: boolean
}

export function EventsRetentionImpactNote({ months, impact, loading }: EventsRetentionImpactNoteProps): JSX.Element {
    if (loading || impact?.retention_months !== months) {
        return (
            <p className="mb-0 flex items-center gap-2 text-secondary" data-attr="events-retention-impact-loading">
                <Spinner /> Counting events
            </p>
        )
    }
    const removed = impact.events_deleted === 0 ? 'no events' : pluralize(impact.events_deleted, 'event')
    return (
        <p className="mb-0 text-secondary" data-attr="events-retention-impact">
            If deletion ran right now, {retentionPeriodLabel(months)} retention would remove {removed}.
        </p>
    )
}
