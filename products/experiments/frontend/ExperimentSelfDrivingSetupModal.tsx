import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconArrowRight, IconCheck, IconGithub, IconSparkles, IconTerminal } from '@posthog/icons'
import { LemonButton, LemonCard, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { OrganizationAI } from 'scenes/settings/organization/OrgAI'
import { urls } from 'scenes/urls'

import { ScoutGitHubConnection } from 'products/signals/frontend/inbox/components/config/scouts/ScoutGitHubConnection'
import { SELF_DRIVING_WIZARD_COMMAND } from 'products/signals/frontend/inbox/components/onboarding/constants'

import { EXPERIMENT_SELF_DRIVING_QUERY_VALUE, experimentScoutLogic } from './experimentScoutLogic'

export function ExperimentSelfDrivingSetupModal({ experimentId }: { experimentId: number }): JSX.Element {
    const logic = experimentScoutLogic({ experimentId })
    const {
        checkingSelfDrivingSetup,
        dataProcessingAccepted,
        githubConnected,
        manualSetupDisabledReason,
        manualSetupReady,
    } = useValues(logic)
    const { checkSelfDrivingSetup, closeExperimentScoutModal, openExperimentScoutSetup } = useActions(logic)

    const githubSetupNextUrl = combineUrl(urls.experiment(experimentId), {
        createScout: EXPERIMENT_SELF_DRIVING_QUERY_VALUE,
    }).url

    return (
        <LemonModal
            isOpen
            width={680}
            title={
                <div className="flex items-center gap-2.5">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded bg-accent-highlight-secondary text-accent">
                        <IconSparkles className="text-lg" />
                    </span>
                    <div className="flex flex-col">
                        <span>Enable Self-driving</span>
                        <span className="text-xs font-normal text-secondary">Step 2 of 3</span>
                    </div>
                </div>
            }
            onClose={closeExperimentScoutModal}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeExperimentScoutModal}>
                        Not now
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        sideIcon={<IconArrowRight />}
                        onClick={openExperimentScoutSetup}
                        disabledReason={manualSetupDisabledReason ?? undefined}
                    >
                        Continue to scout setup
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-5">
                <div>
                    <h3 className="m-0 text-lg">Get the project ready for its scout</h3>
                    <p className="m-0 mt-1 text-sm text-secondary">
                        Self-driving needs AI access and GitHub before it can investigate findings and open pull
                        requests. Use the Wizard or configure both below.
                    </p>
                </div>

                <LemonCard hoverEffect={false} className="overflow-hidden border-accent p-0 shadow-sm">
                    <div className="flex items-start gap-3 border-b border-primary bg-accent-highlight-secondary p-4">
                        <span className="flex size-9 shrink-0 items-center justify-center rounded bg-surface-primary text-accent">
                            <IconTerminal className="text-lg" />
                        </span>
                        <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                                <h4 className="m-0">Set up with the Wizard</h4>
                                <LemonTag type="success" size="small">
                                    Recommended
                                </LemonTag>
                            </div>
                            <p className="m-0 mt-0.5 text-xs text-secondary">
                                Run this command in your product repository. It connects GitHub and configures
                                Self-driving for this project.
                            </p>
                        </div>
                    </div>
                    <div className="flex flex-col gap-3 p-4">
                        <CommandBlock
                            command={SELF_DRIVING_WIZARD_COMMAND}
                            copyLabel="self-driving setup command"
                            ariaLabel="Copy self-driving setup command"
                            decoration="rainbow"
                            size="md"
                            className="!m-0 rounded-md border border-primary bg-surface-secondary hover:border-accent"
                        />
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-xs text-secondary">
                                Finished the Wizard? Check the setup to continue.
                            </span>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={checkSelfDrivingSetup}
                                loading={checkingSelfDrivingSetup}
                            >
                                Check setup
                            </LemonButton>
                        </div>
                    </div>
                </LemonCard>

                <div className="flex items-center gap-3" aria-hidden="true">
                    <span className="h-px flex-1 bg-border-primary" />
                    <span className="text-xs font-medium uppercase tracking-wide text-muted">
                        Or configure manually
                    </span>
                    <span className="h-px flex-1 bg-border-primary" />
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4 shadow-none">
                        <div className="flex items-start justify-between gap-2">
                            <div>
                                <h4 className="m-0">AI processing</h4>
                                <p className="m-0 mt-0.5 text-xs text-secondary">
                                    Allows PostHog to analyze experiment data with AI services.
                                </p>
                            </div>
                            {dataProcessingAccepted ? (
                                <LemonTag type="success" size="small" icon={<IconCheck />}>
                                    Enabled
                                </LemonTag>
                            ) : null}
                        </div>
                        <OrganizationAI />
                    </LemonCard>

                    {githubConnected ? (
                        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4 shadow-none">
                            <div className="flex items-start justify-between gap-2">
                                <div className="flex items-start gap-2.5">
                                    <IconGithub className="mt-0.5 size-4 shrink-0 text-secondary" />
                                    <div>
                                        <h4 className="m-0">GitHub connection</h4>
                                        <p className="m-0 mt-0.5 text-xs text-secondary">
                                            Lets Self-driving read code and open pull requests.
                                        </p>
                                    </div>
                                </div>
                                <LemonTag type="success" size="small" icon={<IconCheck />}>
                                    Connected
                                </LemonTag>
                            </div>
                        </LemonCard>
                    ) : (
                        <ScoutGitHubConnection githubSetupNextUrl={githubSetupNextUrl} />
                    )}
                </div>

                {manualSetupReady ? (
                    <div className="flex items-center gap-2 rounded border border-success bg-success-highlight px-3 py-2 text-sm">
                        <IconCheck className="shrink-0 text-success" />
                        <span>AI processing and GitHub are ready. Creating the scout will finish setup.</span>
                    </div>
                ) : null}
            </div>
        </LemonModal>
    )
}
