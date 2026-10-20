import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { captureInboxWelcomeViewed } from '../../inboxAnalytics'
import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { InboxSetupEmptyState } from './InboxSetupEmptyState'
import { InboxSetupFlow } from './InboxSetupFlow'
import { InboxWelcome } from './InboxWelcome'

export function InboxOnboardingEntry(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { expose, loadSetup } = useActions(inboxSetupLogic)
    const {
        experimentVariant: variant,
        usesFocusedSetup,
        inProgress,
        isQuickSetup,
        savedState,
        savedStateLoading,
        error,
    } = useValues(inboxSetupLogic)
    useEffect(() => {
        if (variant === 'control' || variant === 'test-ui' || variant === 'test-github') {
            expose(variant)
        }
        if (variant === 'test-ui' || variant === 'test-github') {
            captureInboxWelcomeViewed()
        }
    }, [variant, currentTeamId, expose])
    if (!usesFocusedSetup) {
        return <InboxWelcome />
    }
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
