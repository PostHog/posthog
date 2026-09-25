import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { relevancePilotLogic } from '../../logics/relevancePilotLogic'
import { RelevanceShortlist } from './RelevanceShortlist'

export function RelevancePilotContent({ children }: { children: ReactNode }): JSX.Element {
    const { reports, reportsLoading, failed, showQueue, lastSnoozed, lastSnoozedLoading } =
        useValues(relevancePilotLogic)
    const { loadReports, setShowQueue, snooze } = useActions(relevancePilotLogic)
    return showQueue ? (
        <>
            <LemonButton className="m-4" onClick={() => setShowQueue(false)}>
                Back to shortlist
            </LemonButton>
            {children}
        </>
    ) : (
        <RelevanceShortlist
            reports={reports}
            loading={reportsLoading}
            failed={failed}
            saving={lastSnoozedLoading}
            lastSnoozed={lastSnoozed}
            onRetry={loadReports}
            onShowQueue={() => setShowQueue(true)}
            onSnooze={snooze}
        />
    )
}
