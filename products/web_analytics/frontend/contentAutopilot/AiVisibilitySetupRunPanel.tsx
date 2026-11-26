import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Button, Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { AiVisibilityBanner } from './AiVisibilityBanner'
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
                <AiVisibilityBanner type="error" className="mt-3">
                    {startError}
                </AiVisibilityBanner>
            ) : firstRunStep?.status === 'failed' ? (
                <AiVisibilityBanner type="error" className="mt-3">
                    {firstRunStep.detail || "The checks couldn't be queued. Try again."}
                </AiVisibilityBanner>
            ) : null}
            {pollError ? (
                <AiVisibilityBanner type="error" className="mt-3" action={{ children: 'Try again', onClick: retryJob }}>
                    {pollError}
                </AiVisibilityBanner>
            ) : null}
        </>
    )

    if (job && (runInProgress || cancelled)) {
        const settingUp = jobRunning && !jobRef?.onlyFirstRun
        return (
            <Card size="sm" data-attr={cancelled ? 'ai-visibility-setup-cancelled' : 'ai-visibility-setup-running'}>
                <CardHeader>
                    <CardTitle role="heading" aria-level={4}>
                        {cancelled
                            ? 'Setup cancelled'
                            : settingUp
                              ? 'Setting up AI visibility'
                              : 'The first check is running'}
                    </CardTitle>
                    <CardDescription>
                        {cancelled
                            ? `PostHog stopped before it finished. What it saved stays: ${pluralize(savedPrompts, 'prompt')} and ${pluralize(setupContext?.keywords ?? 0, 'keyword')}.${runInProgress ? ' The checks already under way are finishing.' : ''}`
                            : stopRequested
                              ? "Stopping. The checks already under way finish and are kept, and the rest don't run."
                              : settingUp
                                ? 'This takes a few minutes, and you can leave this page. What PostHog saves shows below as it goes.'
                                : 'This takes a few minutes, and you can leave this page. The first results open when every check is in.'}
                    </CardDescription>
                    {cancelled ? null : (
                        <CardAction>
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={cancelSetup}
                                loading={stopping}
                                disabledReason={!settingUp && stopRequested ? 'Stopping the checks' : undefined}
                                data-attr={
                                    settingUp ? 'ai-visibility-setup-cancel' : 'ai-visibility-setup-stop-first-run'
                                }
                            >
                                {settingUp ? 'Cancel setup' : 'Stop the checks'}
                            </Button>
                        </CardAction>
                    )}
                </CardHeader>
                <CardContent>
                    <AiVisibilitySetupChecklist
                        job={job}
                        engineProgress={engineProgress}
                        checksRunning={runInProgress}
                        stopRequested={stopRequested || cancelled}
                    />
                    {banners}
                </CardContent>
            </Card>
        )
    }

    if (savedPrompts === 0) {
        return (
            <AiVisibilityBanner type="info" data-attr="ai-visibility-setup-nothing-saved">
                Setup didn't save any prompts, so there is nothing for the engines to answer. Start again to set up your
                site.
            </AiVisibilityBanner>
        )
    }

    if (hasCurrentChecks) {
        return null
    }

    return (
        <Card size="sm" data-attr="ai-visibility-setup-not-run">
            <CardHeader>
                <CardTitle role="heading" aria-level={4}>
                    The first check hasn't run
                </CardTitle>
                <CardDescription>
                    {stopRequested ? 'You stopped it. ' : ''}Run it now to see your first results in a few minutes. Each
                    engine also checks the prompts that are on, on its schedule.
                </CardDescription>
                <CardAction>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => startFirstRun(activePrompts === 0 && pausedPrompts > 0)}
                        loading={starting}
                        disabledReason={firstRunDisabledReason}
                        data-attr="content-autopilot-first-run-now"
                    >
                        Run the first check
                    </Button>
                </CardAction>
            </CardHeader>
            {startError || firstRunStep?.status === 'failed' || pollError ? <CardContent>{banners}</CardContent> : null}
        </Card>
    )
}
