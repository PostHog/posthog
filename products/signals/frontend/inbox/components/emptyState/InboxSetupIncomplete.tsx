import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { urls } from 'scenes/urls'

import { captureInboxSetupIncompleteViewed, captureInboxSetupRecoveryAction } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { SELF_DRIVING_WIZARD_COMMAND } from '../onboarding/InboxWelcome'

/**
 * What the inbox shows when nothing is watching the project and no setup run is in flight.
 *
 * The waiting state next door promises that agents are working, which holds only while something
 * is enabled. A setup run that ends without turning anything on leaves the same empty inbox, so
 * without this the user reads a reassurance about work that can never arrive. Every route out is
 * on this surface rather than behind a navigation, because the prompt that normally carries the
 * setup command can be suppressed for the rest of the session by one "Set up manually" click.
 */
export function InboxSetupIncomplete(): JSX.Element {
    // The list stays mounted (hidden) while a report, scout, or panel covers it, so gate the view
    // event on the list being the visible surface. Without this a deep link to one of those URLs
    // records a view of a surface the user never saw, and the recovery rate reads lower than it is.
    const { selectedReportId, selectedScoutSkillName, isScratchpadOpen, isFindingsOpen, isRunsOpen, isTriageOpen } =
        useValues(inboxSceneLogic)
    const listVisible =
        !selectedReportId &&
        !selectedScoutSkillName &&
        !isScratchpadOpen &&
        !isFindingsOpen &&
        !isRunsOpen &&
        !isTriageOpen

    const viewedFiredRef = useRef(false)
    useEffect(() => {
        if (listVisible && !viewedFiredRef.current) {
            viewedFiredRef.current = true
            captureInboxSetupIncompleteViewed()
        }
    }, [listVisible])

    return (
        <div className="mx-auto flex max-w-md flex-col items-center gap-2 py-12 text-center">
            <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-fill-primary text-warning">
                <IconWarning className="text-2xl" />
            </div>
            <h3 className="m-0 text-base font-semibold">Setup isn't finished</h3>
            <p className="m-0 text-sm text-tertiary">
                No signal sources or scouts are watching this project, so nothing can reach your inbox yet. If the setup
                agent stopped early, run it again in your repo:
            </p>
            <CommandBlock
                command={SELF_DRIVING_WIZARD_COMMAND}
                copyLabel="self-driving setup command"
                ariaLabel="Copy self-driving setup command"
                decoration="rainbow"
                size="sm"
                onCopy={() => captureInboxSetupRecoveryAction({ action: 'copy_command' })}
                className="!mx-0 !mb-0 !mt-3 rounded-md border border-primary bg-surface-secondary hover:border-accent"
            />
            <p className="m-0 mt-3 text-sm text-tertiary">Or turn on what you want to watch yourself.</p>
            <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
                <LemonButton
                    type="secondary"
                    data-attr="inbox-setup-incomplete-sources"
                    to={urls.inbox('settings')}
                    onClick={() => captureInboxSetupRecoveryAction({ action: 'configure_sources' })}
                >
                    Turn on sources
                </LemonButton>
                <LemonButton
                    type="secondary"
                    data-attr="inbox-setup-incomplete-scouts"
                    to={urls.inbox('scouts')}
                    onClick={() => captureInboxSetupRecoveryAction({ action: 'browse_scouts' })}
                >
                    Browse scouts
                </LemonButton>
            </div>
        </div>
    )
}
