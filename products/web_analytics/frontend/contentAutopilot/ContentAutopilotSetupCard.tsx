import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonCheckbox, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { ContentAutopilotPromptSuggestButton } from './ContentAutopilotPromptSuggestButton'
import { ContentAutopilotSetupCostNote } from './ContentAutopilotSetupCostNote'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'
import { ContentAutopilotSetupProgress } from './ContentAutopilotSetupProgress'
import { unavailableEngineReason } from './utils'

/** The first screen for a project with no prompts: PostHog sets everything up from the site, or the person does it. */
export const ContentAutopilotSetupCard = (): JSX.Element => {
    const {
        setupContext,
        setupContextLoading,
        domain,
        websiteHint,
        selectedEngines,
        startDisabledReason,
        starting,
        startError,
        job,
        jobRunning,
    } = useValues(contentAutopilotSetupLogic)
    const { setDomain, toggleEngine, startSetup, dismissJob } = useActions(contentAutopilotSetupLogic)
    const { openAddPrompts } = useActions(contentAutopilotPromptsLogic)

    if (!setupContext && setupContextLoading) {
        return <LemonSkeleton className="h-96 w-full" />
    }

    if (job) {
        return (
            <LemonCard
                hoverEffect={false}
                className="mx-auto w-full max-w-2xl p-6"
                data-attr="content-autopilot-setup-job"
            >
                <h3 className="m-0">{jobRunning ? 'Setting up AI visibility' : 'Setup finished'}</h3>
                <p className="m-0 mt-1 mb-4 text-muted">
                    {jobRunning
                        ? 'PostHog is reading your site and choosing prompts and keywords. This takes a few minutes, and you can leave this page.'
                        : job.status === 'failed'
                          ? job.error
                          : 'Your prompts and keywords are saved. Review them on the Prompts and Keywords tabs.'}
                </p>
                <ContentAutopilotSetupProgress job={job} />
                {job.status === 'failed' ? (
                    <div className="mt-4 flex justify-end">
                        <LemonButton type="secondary" onClick={dismissJob}>
                            Back to setup
                        </LemonButton>
                    </div>
                ) : null}
            </LemonCard>
        )
    }

    const consentMissing = setupContext ? !setupContext.ai_data_processing_approved : false
    const runDisabledReason =
        startDisabledReason ??
        (setupContext && !setupContext.first_run_available ? "Checks aren't available for this project yet" : undefined)

    return (
        <LemonCard
            hoverEffect={false}
            className="mx-auto w-full max-w-2xl p-6"
            data-attr="content-autopilot-setup-card"
        >
            <h3 className="m-0">Set up AI visibility</h3>
            <p className="m-0 mt-1 text-muted">
                PostHog reads your site, saves the questions your buyers ask AI assistants and the keywords to track,
                then checks how often the answers mention or cite you.
            </p>

            {consentMissing ? (
                <div className="mt-4" data-attr="content-autopilot-setup-consent-banner">
                    <LemonBanner type="warning">
                        Automatic setup needs AI data processing approved for your organization. An admin can approve it
                        in organization settings. You can still add prompts yourself below.
                    </LemonBanner>
                </div>
            ) : null}

            <div className="mt-5 flex flex-col gap-5">
                <LemonField.Pure label="Your site" help={websiteHint ?? undefined}>
                    <LemonInput
                        value={domain}
                        onChange={setDomain}
                        placeholder="example.com"
                        disabledReason={consentMissing ? 'Needs AI data processing approved' : undefined}
                        data-attr="content-autopilot-setup-domain"
                    />
                </LemonField.Pure>

                <LemonField.Pure label="Engines to track" help="Each engine answers every prompt in each run.">
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                        {(setupContext?.engines ?? []).map((setting) => (
                            <LemonCheckbox
                                key={setting.engine}
                                checked={setting.available && selectedEngines.includes(setting.engine)}
                                onChange={(checked) => toggleEngine(setting.engine, checked)}
                                disabledReason={unavailableEngineReason(setting)}
                                label={
                                    <span className="flex flex-col">
                                        <ContentAutopilotEngineLabel engine={setting.engine} />
                                        {setting.available ? null : (
                                            <span className="text-xs text-muted">
                                                {unavailableEngineReason(setting)}
                                            </span>
                                        )}
                                    </span>
                                }
                                data-attr="content-autopilot-setup-engine"
                            />
                        ))}
                    </div>
                </LemonField.Pure>

                <ContentAutopilotSetupCostNote
                    prompts={setupContext?.prompt_target ?? 0}
                    engines={selectedEngines.length}
                />
            </div>

            {startError ? (
                <LemonBanner type="error" className="mt-4">
                    {startError}
                </LemonBanner>
            ) : null}

            <div className="mt-6 flex flex-wrap justify-end gap-2">
                <LemonButton
                    type="secondary"
                    onClick={() => startSetup(false)}
                    loading={starting}
                    disabledReason={startDisabledReason}
                    data-attr="content-autopilot-setup-configure-only"
                >
                    Configure only
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={() => startSetup(true)}
                    loading={starting}
                    disabledReason={runDisabledReason}
                    data-attr="content-autopilot-setup-run-once"
                >
                    Set up and run once
                </LemonButton>
            </div>

            <div className="mt-6 border-t pt-4">
                <p className="m-0 mb-2 text-xs text-secondary">Or choose your prompts yourself.</p>
                <div className="flex flex-wrap gap-2">
                    <ContentAutopilotPromptSuggestButton type="secondary" />
                    <LemonButton
                        type="secondary"
                        icon={<IconPlusSmall />}
                        onClick={openAddPrompts}
                        data-attr="content-autopilot-setup-add-own"
                    >
                        Add my own
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}
