import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { cn } from 'lib/utils/css-classes'
import { onboardingEventUsageLogic } from 'scenes/onboarding/onboardingEventUsageLogic'
import { currentTaskLabel, syncHeadline, toneTextClass } from 'scenes/onboarding/shared/wizard-sync/helpers'
import { useRunElapsedSeconds } from 'scenes/onboarding/shared/wizard-sync/hooks'
import { installationProgressLogic } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'
import { PipStrip } from 'scenes/onboarding/shared/wizard-sync/PipStrip'
import { StatusGlyph } from 'scenes/onboarding/shared/wizard-sync/StatusGlyph'
import { WizardSyncDialog } from 'scenes/onboarding/shared/wizard-sync/WizardSyncDialog'
import { wizardSyncUiLogic } from 'scenes/onboarding/shared/wizard-sync/wizardSyncUiLogic'

/**
 * Rail-sized summary of a live wizard run: glyph + headline, the step it is on, and the pip strip.
 * A miniature of the detached widget's collapsed card, restyled to sit among the setup widgets.
 * Clicking it opens the same "all the details" dialog the detached widget uses.
 */
export function InstallationCard({ workflowId }: { workflowId: string }): JSX.Element {
    const { installationProgress, latestSession } = useValues(installationProgressLogic({ mode: 'local', workflowId }))
    const { claimInlinePanel, releaseInlinePanel } = useActions(wizardSyncUiLogic)
    const { dialogOpen } = useValues(wizardSyncUiLogic)
    const { openDialog, closeDialog, openHandoffDoc } = useActions(wizardSyncUiLogic)
    const { reportWizardSyncHandoffDocOpened } = useActions(onboardingEventUsageLogic)

    // This card is the local run's surface while the rail shows it, so the detached widget stands
    // down for that run. A cloud run in flight at the same time keeps its own surface.
    useEffect(() => {
        claimInlinePanel('local')
        return () => releaseInlinePanel('local')
    }, [claimInlinePanel, releaseInlinePanel])

    // Elapsed clock, frozen at the run's last update once it reaches a terminal phase.
    const isTerminal = installationProgress.phase === 'completed' || installationProgress.phase === 'error'
    const elapsedSeconds = useRunElapsedSeconds(
        latestSession?.started_at,
        isTerminal ? latestSession?.updated_at : null
    )

    // `currentTaskLabel` over the raw step so a run waiting on the user surfaces the question
    // it is blocked on, which is the whole point of noticing it from here.
    const detail = currentTaskLabel(installationProgress)

    const handoffText = installationProgress.handoffText
    const runKey = latestSession?.session_id
    const handleViewReport =
        handoffText && runKey
            ? () => {
                  reportWizardSyncHandoffDocOpened({ runKey, mode: 'local', trigger: 'button' })
                  openHandoffDoc({ key: runKey, text: handoffText })
              }
            : undefined
    return (
        <>
            <button
                type="button"
                onClick={openDialog}
                aria-label="Show setup progress details"
                data-attr="inbox-installation-widget"
                className="flex flex-col gap-1.5 rounded border border-primary bg-surface-primary px-2.5 py-2 text-left cursor-pointer transition-colors hover:border-secondary"
            >
                <div className="flex items-center gap-2 min-w-0 w-full">
                    <span className="shrink-0 [&_svg]:size-4 [&_.Spinner]:text-base">
                        <StatusGlyph progress={installationProgress} />
                    </span>
                    <span className={cn('text-[13px] font-medium truncate', toneTextClass(installationProgress))}>
                        {syncHeadline(installationProgress)}
                    </span>
                </div>
                {/* Wizard-supplied, so it can carry project detail that must not reach autocapture
                    — and this whole card is a clickable element, whose text autocapture would take. */}
                {detail && <p className="m-0 text-xs text-secondary truncate w-full ph-no-capture">{detail}</p>}
                <PipStrip steps={installationProgress.steps} />
            </button>
            <WizardSyncDialog
                progress={installationProgress}
                elapsedSeconds={elapsedSeconds}
                mode="local"
                isOpen={dialogOpen}
                onClose={closeDialog}
                onViewReport={handleViewReport}
            />
        </>
    )
}
