import { useActions, useValues } from 'kea'

import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

import { TransactionalEmailClickTimeline } from './TransactionalEmailClickTimeline'
import { transactionalEmailLogEntryLogic } from './transactionalEmailLogEntryLogic'

export function TransactionalEmailClickCard({ email }: { email: TransactionalEmailLogDetailApi }): JSX.Element | null {
    const { outcomesShown, outcomeRows, activityFailed, activityDenied, activityLoading } = useValues(
        transactionalEmailLogEntryLogic
    )
    const { loadActivity } = useActions(transactionalEmailLogEntryLogic)

    if (!outcomesShown) {
        return null
    }
    return (
        <TransactionalEmailClickTimeline
            rows={outcomeRows}
            failed={activityFailed && !activityLoading}
            denied={activityDenied && !activityLoading}
            onRetry={loadActivity}
            clickTracking={email.tracking.clicks}
        />
    )
}
