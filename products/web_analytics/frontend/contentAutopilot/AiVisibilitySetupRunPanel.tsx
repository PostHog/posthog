import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { AiVisibilitySetupChecklist } from './AiVisibilitySetupChecklist'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

export const AiVisibilitySetupRunPanel = (): JSX.Element | null => {
    const {
        job,
        jobRef,
        jobRunning,
        runInProgress,
        firstRunQueued,
        firstRunStep,
        firstChecksWatching,
        engineProgress,
        hasCurrentChecks,
        firstRunDisabledReason,
        stopRequested,
        stopping,
        setupContext,
        starting,
        startError,
        pollError,
    } = useValues(contentAutopilotSetupLogic)
    const { cancelSetup, resumeFirstChecks, startFirstRun, retryJob } = useActions(contentAutopilotSetupLogic)

    useEffect(() => {
        if (firstRunQueued && !jobRunning && !firstChecksWatching && setupContext) {
            resumeFirstChecks()
        }
    }, [firstRunQueued, jobRunning, firstChecksWatching, setupContext, resumeFirstChecks])

    const cancelled = job?.status === 'cancelled'
    const activePrompts = setupContext?.active_prompts ?? 0
    const pausedPrompts = setupContext?.paused_prompts ?? 0
    const savedPrompts = activePrompts + pausedPrompts
    const banners = (
        <>
            {startError ? (
                <LemonBanner type="error" className="mt-3">
                    {startError}
                </LemonBanner>
            ) : firstRunStep?.status === 'failed' ? (
                <LemonBanner type="error" className="mt-3">
                    {firstRunStep.detail || "The checks couldn't be queued. Try again."}
                </LemonBanner>
            ) : null}
            {pollError ? (
                <LemonBanner type="error" className="mt-3" action={{ children: 'Try again', onClick: retryJob }}>
                    {pollError}
                </LemonBanner>
            ) : null}
        </>
    )

    if (job && (runInProgress || cancelled)) {
        const settingUp = jobRunning && !jobRef?.onlyFirstRun
        return (
            <LemonCard
                hoverEffect={false}
                className="p-4"
                data-attr={cancelled ? 'ai-visibility-setup-cancelled' : 'ai-visibility-setup-running'}
            >
                <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 basis-80">
                        <h4 className="m-0">
                            {cancelled
                                ? 'Setup cancelled'
                                : settingUp
                                  ? 'Setting up AI visibility'
                                  : 'The first check is running'}
                        </h4>
                        <p className="m-0 mt-1 text-xs text-secondary">
                            {cancelled
                                ? `PostHog stopped before it finished. What it saved stays: ${pluralize(savedPrompts, 'prompt')} and ${pluralize(setupContext?.keywords ?? 0, 'keyword')}.${runInProgress ? ' The checks already under way are finishing.' : ''}`
                                : stopRequested
                                  ? "Stopping. The checks already under way finish and are kept, and the rest don't run."
                                  : settingUp
                                    ? 'This takes a few minutes, and you can leave this page. What PostHog saves shows below as it goes.'
                                    : 'This takes a few minutes, and you can leave this page. The first results open when every check is in.'}
                        </p>
                    </div>
                    {cancelled ? null : (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={cancelSetup}
                            loading={stopping}
                            disabledReason={!settingUp && stopRequested ? 'Stopping the checks' : undefined}
                            data-attr={settingUp ? 'ai-visibility-setup-cancel' : 'ai-visibility-setup-stop-first-run'}
                        >
                            {settingUp ? 'Cancel setup' : 'Stop the checks'}
                        </LemonButton>
                    )}
                </div>
                <AiVisibilitySetupChecklist
                    job={job}
                    engineProgress={engineProgress}
                    checksRunning={runInProgress}
                    stopRequested={stopRequested || cancelled}
                />
                {banners}
            </LemonCard>
        )
    }

    if (savedPrompts === 0) {
        return (
            <LemonBanner type="info" data-attr="ai-visibility-setup-nothing-saved">
                Setup didn't save any prompts, so there is nothing for the engines to answer. Start again to set up your
                site.
            </LemonBanner>
        )
    }

    if (hasCurrentChecks) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-4" data-attr="ai-visibility-setup-not-run">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0 flex-1 basis-80">
                    <h4 className="m-0">The first check hasn't run</h4>
                    <p className="m-0 mt-1 text-xs text-secondary">
                        {stopRequested ? 'You stopped it. ' : ''}Run it now to see your first results in a few minutes.
                        Each engine also checks the prompts that are on, on its schedule.
                    </p>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => startFirstRun(activePrompts === 0 && pausedPrompts > 0)}
                    loading={starting}
                    disabledReason={firstRunDisabledReason}
                    data-attr="content-autopilot-first-run-now"
                >
                    Run the first check
                </LemonButton>
            </div>
            {banners}
        </LemonCard>
    )
}
