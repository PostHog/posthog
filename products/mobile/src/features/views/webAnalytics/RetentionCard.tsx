import type { ReactElement } from 'react'

import type { InsightSnapshot } from '@/model/views'
import { RetentionGrid } from '@/ui/chart/RetentionGrid'

import { useWebItemData, type WebItemRef } from './hooks'
import { WebCard, webCardState } from './WebCard'

export function RetentionCard({ data }: { data: WebItemRef }): ReactElement {
    const item = useWebItemData<InsightSnapshot>(data)
    const retention = item.snapshot?.retention ?? null
    return (
        <WebCard
            title="Retention"
            meta="Weekly cohorts"
            state={webCardState(item, Boolean(retention?.cohorts.length))}
            error={item.error}
            stale={item.snapshot?.refreshFailed ?? false}
            updating={item.updating}
            loadingHeight={200}
            testID="web-retention"
        >
            {retention ? (
                <RetentionGrid
                    retention={retention}
                    label="Retention"
                    selectionId="web-retention"
                    trackingContext="view"
                    testID="web-retention-grid"
                />
            ) : null}
        </WebCard>
    )
}
