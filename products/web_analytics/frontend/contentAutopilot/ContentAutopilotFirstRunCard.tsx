import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowRight } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardGroup,
    CardHeader,
    CardTitle,
    Spinner,
    Text,
} from '@posthog/quill'

import { AiVisibilityBanner } from './AiVisibilityBanner'
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

    const runNow = paused
        ? {
              title: 'Your prompts are saved, paused',
              description: `Nothing runs and nothing is spent until you turn them on. Run your ${prompts} prompts once to see your first results.`,
              label: 'Turn on and run once',
              dataAttr: 'content-autopilot-first-run-activate',
          }
        : {
              title: 'Your prompts are ready',
              description: 'Each engine runs the first checks on its schedule. To see results sooner, run them now.',
              label: 'Run checks now',
              dataAttr: 'content-autopilot-first-run-now',
          }

    return (
        <div className="flex flex-col gap-4" data-attr="content-autopilot-first-run">
            <Card>
                {firstRunQueued ? (
                    <CardHeader data-attr="content-autopilot-first-run-queued">
                        <CardTitle role="heading" aria-level={3}>
                            The first checks are running
                        </CardTitle>
                        <CardDescription>
                            Each engine is answering your prompts. This page updates as the checks finish, which takes a
                            few minutes.
                        </CardDescription>
                    </CardHeader>
                ) : jobRunning ? (
                    <CardHeader data-attr="content-autopilot-first-run-starting">
                        <CardTitle role="heading" aria-level={3} className="flex items-center gap-2">
                            <Spinner />
                            Queuing the first checks
                        </CardTitle>
                    </CardHeader>
                ) : (
                    <>
                        <CardHeader>
                            <CardTitle role="heading" aria-level={3}>
                                {runNow.title}
                            </CardTitle>
                            <CardDescription>{runNow.description}</CardDescription>
                        </CardHeader>
                        <CardContent className="flex flex-wrap items-end justify-between gap-4">
                            <div className="min-w-0 flex-1 basis-80">
                                <ContentAutopilotSetupCostNote prompts={prompts} engines={activeEngineCount} />
                            </div>
                            <Button
                                variant="primary"
                                onClick={() => startFirstRun(paused)}
                                loading={starting}
                                disabledReason={firstRunDisabledReason}
                                data-attr={runNow.dataAttr}
                            >
                                {runNow.label}
                            </Button>
                        </CardContent>
                    </>
                )}
                {startError || firstRunStep?.status === 'failed' || (skipReason && !firstRunQueued) || pollError ? (
                    <CardFooter className="flex flex-col items-stretch gap-2">
                        {startError ? (
                            <AiVisibilityBanner type="error">{startError}</AiVisibilityBanner>
                        ) : firstRunStep?.status === 'failed' ? (
                            <AiVisibilityBanner
                                type="error"
                                action={{ children: 'Try again', onClick: () => startFirstRun(paused) }}
                            >
                                {firstRunStep.detail || "The checks couldn't be queued. Try again."}
                            </AiVisibilityBanner>
                        ) : skipReason && !firstRunQueued ? (
                            <AiVisibilityBanner type="info" onClose={dismissJob}>
                                {skipReason}
                            </AiVisibilityBanner>
                        ) : null}
                        {pollError ? (
                            <AiVisibilityBanner
                                type="error"
                                action={{ children: 'Try again', onClick: retryJob }}
                                onClose={dismissJob}
                            >
                                {pollError}
                            </AiVisibilityBanner>
                        ) : null}
                    </CardFooter>
                ) : null}
            </Card>
            <CardGroup role="list">
                {CHECKLIST.map((item) => (
                    <Card key={item.tab} size="sm" className="p-0" role="listitem">
                        <button
                            type="button"
                            onClick={() => setWorkspaceTab(item.tab)}
                            className="flex w-full min-w-0 cursor-pointer items-center gap-3 px-3 py-2.5 text-start hover:bg-fill-hover"
                            data-attr={`content-autopilot-first-run-${item.tab}`}
                        >
                            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                                <Text size="sm" weight="medium" render={<span className="m-0" />}>
                                    {item.label}
                                </Text>
                                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                    {item.detail}
                                </Text>
                            </span>
                            <IconArrowRight className="shrink-0 text-muted-foreground" />
                        </button>
                    </Card>
                ))}
            </CardGroup>
        </div>
    )
}
