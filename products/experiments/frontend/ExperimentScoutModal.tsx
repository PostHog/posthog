import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import React from 'react'

import { IconArrowRight, IconBell, IconCheckCircle, IconPulse, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { EXPERIMENT_SCOUT_QUERY_VALUE, experimentScoutLogic } from './experimentScoutLogic'
import { ExperimentSelfDrivingSetupModal } from './ExperimentSelfDrivingSetupModal'

const LazyScoutCreateModal = React.lazy(async () => {
    const { ScoutCreateModal } =
        await import('products/signals/frontend/inbox/components/config/scouts/ScoutCreateModal')
    return { default: ScoutCreateModal }
})

export function ExperimentScoutModal({ experimentId }: { experimentId: number }): JSX.Element | null {
    const logic = experimentScoutLogic({ experimentId })
    const { experimentScoutModalStep, experimentScoutSetupStatus, scoutInitialValues } = useValues(logic)
    const { closeExperimentScoutModal, continueFromLaunch } = useActions(logic)

    if (experimentScoutModalStep === null || !experimentScoutSetupStatus?.enrolled) {
        return null
    }

    if (experimentScoutModalStep === 'launch-success') {
        return (
            <LemonModal
                isOpen
                width={600}
                title={
                    <div className="flex items-center gap-2.5">
                        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-success-highlight">
                            <IconCheckCircle className="text-success text-xl" />
                        </span>
                        <div className="flex flex-col">
                            <span>Your experiment has been launched</span>
                            <span className="text-xs font-normal text-secondary">Step 1 of 3</span>
                        </div>
                    </div>
                }
                onClose={closeExperimentScoutModal}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={closeExperimentScoutModal}>
                            Not now
                        </LemonButton>
                        <LemonButton type="primary" sideIcon={<IconArrowRight />} onClick={continueFromLaunch}>
                            Set up a scout
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-4">
                    <p className="m-0 text-base text-secondary">
                        Your experiment is live and collecting data. A scout can monitor it while it runs.
                    </p>

                    <div className="overflow-hidden rounded-lg border border-primary">
                        <div className="flex items-start gap-3 bg-surface-secondary p-4">
                            <span className="flex size-9 shrink-0 items-center justify-center rounded bg-accent-highlight-secondary text-accent">
                                <IconSparkles className="text-lg" />
                            </span>
                            <div className="flex flex-col gap-1">
                                <h4 className="m-0">What the scout watches</h4>
                                <p className="m-0 text-sm text-secondary">
                                    A scout reviews the experiment each day and reports findings that could affect your
                                    decision.
                                </p>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 border-t border-primary sm:grid-cols-2 sm:divide-x sm:divide-primary">
                            <div className="flex items-start gap-3 p-4">
                                <IconPulse className="mt-0.5 shrink-0 text-lg text-muted" />
                                <div className="flex flex-col gap-1">
                                    <span className="font-medium">Data quality</span>
                                    <span className="text-xs text-secondary">
                                        Exposure balance, contamination, and stalled exposure.
                                    </span>
                                </div>
                            </div>
                            <div className="flex items-start gap-3 border-t border-primary p-4 sm:border-t-0">
                                <IconSparkles className="mt-0.5 shrink-0 text-lg text-muted" />
                                <div className="flex flex-col gap-1">
                                    <span className="font-medium">Results</span>
                                    <span className="text-xs text-secondary">
                                        Meaningful changes across variants and metrics.
                                    </span>
                                </div>
                            </div>
                        </div>

                        <div className="flex items-center gap-2.5 border-t border-primary bg-surface-secondary px-4 py-3 text-sm text-secondary">
                            <IconBell className="shrink-0 text-base" />
                            <span>Findings appear in your inbox and can also be sent to Slack.</span>
                        </div>
                    </div>
                </div>
            </LemonModal>
        )
    }

    if (experimentScoutModalStep === 'self-driving-setup') {
        return <ExperimentSelfDrivingSetupModal experimentId={experimentId} />
    }

    const githubSetupNextUrl = combineUrl(urls.experiment(experimentId), {
        createScout: EXPERIMENT_SCOUT_QUERY_VALUE,
    }).url

    return (
        <React.Suspense fallback={null}>
            <LazyScoutCreateModal
                isOpen
                title="Set up an experiment scout"
                description="Step 3 of 3. Review the instructions, then choose when the scout runs and where it sends findings."
                initialValues={scoutInitialValues}
                showGitHubConnection
                githubSetupNextUrl={githubSetupNextUrl}
                onClose={closeExperimentScoutModal}
            />
        </React.Suspense>
    )
}
