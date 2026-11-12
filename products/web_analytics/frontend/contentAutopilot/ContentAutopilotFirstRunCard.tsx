import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

import { contentAutopilotLogic } from './contentAutopilotLogic'
import { ContentAutopilotSetupCostNote } from './ContentAutopilotSetupCostNote'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

const CHECKLIST = [
    { tab: 'prompts', label: 'Review your prompts', detail: 'Edit or pause the questions PostHog saved.' },
    { tab: 'keywords', label: 'Review your keywords', detail: "Remove any you don't need." },
    { tab: 'settings', label: 'Choose engines', detail: 'Turn engines on or off and set how often they run.' },
] as const

const SKIP_REASONS: Record<string, string> = {
    not_available: "Checks aren't available for this project yet.",
    nothing_to_run:
        'Checks need your brand and at least one active prompt. Add them in settings and on the Prompts tab.',
    already_run: 'Checks already ran for this project.',
}

/** The overview of a project that has prompts but no checks yet. `paused` is set when every prompt is turned off. */
export const ContentAutopilotFirstRunCard = ({
    prompts,
    paused = false,
}: {
    prompts: number
    paused?: boolean
}): JSX.Element => {
    const {
        activeEngineCount,
        firstRunDisabledReason,
        starting,
        startError,
        jobRunning,
        firstRunQueued,
        firstRunStep,
        pollError,
    } = useValues(contentAutopilotSetupLogic)
    const { startFirstRun, retryJob, dismissJob, watchFirstChecks } = useActions(contentAutopilotSetupLogic)
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)

    // After a reload the overview still has to notice when the queued checks land.
    useEffect(() => {
        if (firstRunQueued) {
            watchFirstChecks()
        }
    }, [firstRunQueued, watchFirstChecks])

    const skipReason =
        firstRunStep?.status === 'skipped' && firstRunStep.detail ? SKIP_REASONS[firstRunStep.detail] : undefined

    return (
        <LemonCard hoverEffect={false} className="p-6" data-attr="content-autopilot-first-run">
            {firstRunQueued ? (
                <div data-attr="content-autopilot-first-run-queued">
                    <h3 className="m-0">The first checks are running</h3>
                    <p className="m-0 mt-1 text-muted">
                        Each engine is answering your prompts. This page updates as the checks finish, which takes a few
                        minutes.
                    </p>
                </div>
            ) : jobRunning ? (
                <div className="flex items-center gap-2" data-attr="content-autopilot-first-run-starting">
                    <Spinner />
                    <h3 className="m-0">Queuing the first checks</h3>
                </div>
            ) : paused ? (
                <>
                    <h3 className="m-0">Your prompts are saved, paused</h3>
                    <p className="m-0 mt-1 text-muted">
                        Nothing is checked yet, so nothing is spent. Turn on your {prompts} prompts and run them once to
                        see where you stand. After that, each engine checks them on its schedule.
                    </p>
                    <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
                        <div className="min-w-0 flex-1 basis-80">
                            <ContentAutopilotSetupCostNote prompts={prompts} engines={activeEngineCount} />
                        </div>
                        <LemonButton
                            type="primary"
                            onClick={() => startFirstRun(true)}
                            loading={starting}
                            disabledReason={firstRunDisabledReason}
                            data-attr="content-autopilot-first-run-activate"
                        >
                            Turn on and run once
                        </LemonButton>
                    </div>
                </>
            ) : (
                <>
                    <h3 className="m-0">Your prompts are ready</h3>
                    <p className="m-0 mt-1 text-muted">
                        Each engine runs the first checks on its schedule. To see results sooner, run them now.
                    </p>
                    <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
                        <div className="min-w-0 flex-1 basis-80">
                            <ContentAutopilotSetupCostNote prompts={prompts} engines={activeEngineCount} />
                        </div>
                        <LemonButton
                            type="primary"
                            onClick={() => startFirstRun(false)}
                            loading={starting}
                            disabledReason={firstRunDisabledReason}
                            data-attr="content-autopilot-first-run-now"
                        >
                            Run checks now
                        </LemonButton>
                    </div>
                </>
            )}
            {startError ? (
                <LemonBanner type="error" className="mt-4">
                    {startError}
                </LemonBanner>
            ) : firstRunStep?.status === 'failed' ? (
                <LemonBanner
                    type="error"
                    className="mt-4"
                    action={{ children: 'Try again', onClick: () => startFirstRun(paused) }}
                >
                    {firstRunStep.detail || "The checks couldn't be queued. Try again."}
                </LemonBanner>
            ) : skipReason && !firstRunQueued ? (
                <LemonBanner type="info" className="mt-4" onClose={dismissJob}>
                    {skipReason}
                </LemonBanner>
            ) : null}
            {pollError ? (
                <LemonBanner
                    type="error"
                    className="mt-4"
                    action={{ children: 'Try again', onClick: retryJob }}
                    onClose={dismissJob}
                >
                    {pollError}
                </LemonBanner>
            ) : null}
            <ul className="m-0 mt-5 flex list-none flex-col gap-2 border-t p-0 pt-4">
                {CHECKLIST.map((item) => (
                    <li key={item.tab}>
                        <LemonButton
                            fullWidth
                            sideIcon={<IconArrowRight />}
                            onClick={() => setWorkspaceTab(item.tab)}
                            data-attr={`content-autopilot-first-run-${item.tab}`}
                        >
                            <span className="flex flex-col items-start">
                                <span>{item.label}</span>
                                <span className="text-xs font-normal text-secondary">{item.detail}</span>
                            </span>
                        </LemonButton>
                    </li>
                ))}
            </ul>
        </LemonCard>
    )
}
