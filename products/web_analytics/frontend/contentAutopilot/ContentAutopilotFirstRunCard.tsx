import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { Button, Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@posthog/quill'

import { AiVisibilityAddBrandForm } from './AiVisibilityAddBrandForm'
import { AiVisibilityBanner } from './AiVisibilityBanner'
import { ContentAutopilotSetupCostNote } from './ContentAutopilotSetupCostNote'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

const SKIP_REASONS: Record<string, string> = {
    not_available: "Checks aren't available for this project yet.",
    nothing_to_run: 'Checks need your brand and at least one active prompt. Turn on a prompt on the Prompts tab.',
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
        firstRunQueued,
        firstRunStep,
        pollError,
        setupContext,
    } = useValues(contentAutopilotSetupLogic)
    const { startFirstRun, retryJob, dismissJob, setWizardStep } = useActions(contentAutopilotSetupLogic)

    const needsBrand = !!setupContext && setupContext.own_domains.length === 0

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
              description: 'Each engine checks your prompts on its schedule. To see results sooner, run them now.',
              label: 'Run checks now',
              dataAttr: 'content-autopilot-first-run-now',
          }

    return (
        <Card data-attr="content-autopilot-first-run">
            {needsBrand ? (
                <>
                    <CardHeader data-attr="content-autopilot-first-run-needs-brand">
                        <CardTitle role="heading" aria-level={3}>
                            Set your brand to run the checks
                        </CardTitle>
                        <CardDescription>
                            PostHog counts an answer as yours when it names or links to this site.
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        <AiVisibilityAddBrandForm formKey="first-run" kinds={['own']} placeholder="yoursite.com" />
                    </CardContent>
                </>
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
                <CardContent className="flex flex-col gap-2">
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
                </CardContent>
            ) : null}
            <CardFooter className="flex justify-end">
                <Button
                    variant="outline"
                    onClick={() => setWizardStep('review')}
                    data-attr="content-autopilot-first-run-review"
                >
                    Review your setup
                    <IconArrowRight />
                </Button>
            </CardFooter>
        </Card>
    )
}
