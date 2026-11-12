import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type { AEOSetupJobApi, AEOSetupStepApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'
import { ContentAutopilotSetupProgress } from './ContentAutopilotSetupProgress'

const step = (job: AEOSetupJobApi, name: AEOSetupStepApi['step']): AEOSetupStepApi | undefined =>
    job.steps.find((item) => item.step === name)

/** What a finished job did, one sentence per step that matters. */
const outcome = (job: AEOSetupJobApi): string[] => {
    const prompts = step(job, 'prompts')
    const keywords = step(job, 'keywords')
    const firstRun = step(job, 'first_run')
    const lines: string[] = []
    if (prompts?.status === 'done') {
        lines.push(`Added ${pluralize(prompts.added ?? 0, 'prompt')}.`)
    } else if (prompts?.status === 'skipped') {
        lines.push('Kept your existing prompts.')
    }
    if (keywords?.status === 'done') {
        lines.push(`Added ${pluralize(keywords.added ?? 0, 'keyword')}.`)
    } else if (keywords?.status === 'failed') {
        lines.push(`Keywords couldn't be suggested. ${keywords.detail ?? ''} You can add them on the Keywords tab.`)
    }
    if (firstRun?.status === 'done') {
        lines.push('The first checks are queued. Results show up on the overview as they finish.')
    } else if (firstRun?.status === 'failed') {
        lines.push(firstRun.detail || "The first checks couldn't be queued. Run them from the overview.")
    } else if (firstRun?.detail === 'not_available') {
        lines.push("Checks aren't available for this project yet.")
    } else if (firstRun?.status === 'skipped') {
        lines.push("The first checks run on each engine's schedule.")
    }
    return lines
}

/** A setup job while it runs, and what it did once it finishes. */
export const ContentAutopilotSetupJobCard = ({ job }: { job: AEOSetupJobApi }): JSX.Element => {
    const { pollError } = useValues(contentAutopilotSetupLogic)
    const { dismissJob, retryJob } = useActions(contentAutopilotSetupLogic)
    const running = job.status === 'pending'

    return (
        <LemonCard hoverEffect={false} className="mx-auto w-full max-w-2xl p-6" data-attr="content-autopilot-setup-job">
            <h3 className="m-0">
                {running ? 'Setting up AI visibility' : job.status === 'failed' ? 'Setup stopped' : 'Setup finished'}
            </h3>
            <div className="mt-1 mb-4 flex flex-col gap-1 text-muted">
                {running ? (
                    <p className="m-0">
                        PostHog is reading your site and choosing prompts and keywords. This takes a few minutes, and
                        you can leave this page.
                    </p>
                ) : job.status === 'failed' ? (
                    <p className="m-0">{job.error}</p>
                ) : (
                    outcome(job).map((line) => (
                        <p key={line} className="m-0">
                            {line}
                        </p>
                    ))
                )}
            </div>
            <ContentAutopilotSetupProgress job={job} />
            {pollError ? (
                <LemonBanner type="error" className="mt-4" action={{ children: 'Try again', onClick: retryJob }}>
                    {pollError}
                </LemonBanner>
            ) : null}
            {!running || pollError ? (
                <div className="mt-4 flex justify-end">
                    <LemonButton type="secondary" onClick={dismissJob} data-attr="content-autopilot-setup-dismiss">
                        {job.status === 'failed' ? 'Back to setup' : 'Done'}
                    </LemonButton>
                </div>
            ) : null}
        </LemonCard>
    )
}
