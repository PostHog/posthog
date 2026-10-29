import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { captureInboxWelcomeViewed } from '../../inboxAnalytics'
import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { InboxSetupEmptyState } from './InboxSetupEmptyState'
import { InboxSetupFlow } from './InboxSetupFlow'

export function InboxOnboardingEntry(): JSX.Element {
    const { expose, loadSetup } = useActions(inboxSetupLogic)
    const { currentTeamId, inProgress, isQuickSetup, savedState, savedStateLoading, error } = useValues(inboxSetupLogic)
    useEffect(() => {
        expose()
        captureInboxWelcomeViewed()
    }, [currentTeamId, expose])
    if (!savedState && !inProgress) {
        return (
            <div className="mx-auto w-full max-w-2xl px-6 py-8">
                {error ? (
                    <LemonBanner type="error">
                        <span>{error}</span>
                        <LemonButton size="small" onClick={loadSetup} loading={savedStateLoading}>
                            Retry
                        </LemonButton>
                    </LemonBanner>
                ) : (
                    <LemonSkeleton className="h-80" />
                )}
            </div>
        )
    }
    return inProgress && !isQuickSetup ? <InboxSetupFlow /> : <InboxSetupEmptyState />
}
