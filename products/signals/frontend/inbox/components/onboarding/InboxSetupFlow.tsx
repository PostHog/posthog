import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { GuidedWizardPanel } from 'lib/components/GuidedWizard/GuidedWizardPanel'
import { GuidedWizardStepper } from 'lib/components/GuidedWizard/GuidedWizardStepper'
import { cn } from 'lib/utils/css-classes'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { scoutSuggestionsLogic } from '../../logics/scoutSuggestionsLogic'
import { InboxSetupGithubStep } from './InboxSetupGithubStep'
import { InboxSetupScoutsStep } from './InboxSetupScoutsStep'
import { InboxSetupSourcesStep } from './InboxSetupSourcesStep'

export function InboxSetupFlow(): JSX.Element {
    const { draft, ready, saving, error, activationDisabledReason, isFinalStep, currentTeamId } =
        useValues(inboxSetupLogic)
    const { startSetup, goToStep, activate, retry, reportStepViewed } = useActions(inboxSetupLogic)
    useMountedLogic(scoutSuggestionsLogic)
    useEffect(() => {
        startSetup()
    }, [startSetup])
    useEffect(() => {
        if (ready) {
            reportStepViewed()
        }
    }, [ready, draft.step, currentTeamId, reportStepViewed])
    const isScoutsStep = draft.step === 'scouts'
    return (
        <div className={cn('@container w-full', isScoutsStep && 'h-full')}>
            <div
                className={cn(
                    'mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-8',
                    isScoutsStep && 'h-full min-h-0'
                )}
            >
                <div className="shrink-0">
                    <h1 className="text-2xl font-semibold m-0">Set up Self-Driving</h1>
                    <p className="mt-2 mb-0 max-w-2xl text-secondary">
                        Choose your sources and scouts, then review and activate.
                    </p>
                </div>
                <GuidedWizardStepper
                    steps={[
                        { step: 'signals', label: 'Sources' },
                        { step: 'scouts', label: 'Scouts' },
                        { step: 'github', label: 'Review and activate' },
                    ]}
                    currentStep={draft.step}
                    onStepClick={saving || !ready ? undefined : goToStep}
                    className="shrink-0 flex-nowrap overflow-x-auto whitespace-nowrap py-1 [&>div]:shrink-0"
                    aria-label="Self-Driving setup progress"
                />
                <GuidedWizardPanel className={cn('p-5 @lg:p-6 space-y-6', isScoutsStep && 'flex min-h-0 flex-col')}>
                    {draft.step === 'signals' ? (
                        <InboxSetupSourcesStep />
                    ) : draft.step === 'scouts' ? (
                        <InboxSetupScoutsStep />
                    ) : (
                        <InboxSetupGithubStep />
                    )}
                    {error && (
                        <LemonBanner type="error">
                            <span>{error}</span>
                            <LemonButton size="small" onClick={retry} loading={saving}>
                                Retry
                            </LemonButton>
                        </LemonBanner>
                    )}
                    <div className="flex shrink-0 flex-wrap justify-between items-center gap-3 border-t border-primary pt-4">
                        {draft.step !== 'signals' && (
                            <LemonButton
                                type="secondary"
                                icon={<IconArrowLeft />}
                                disabled={saving}
                                onClick={() => goToStep(draft.step === 'github' ? 'scouts' : 'signals')}
                            >
                                Back
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            className="ml-auto"
                            status="alt"
                            loading={saving}
                            disabledReason={
                                !ready ? 'Loading your setup' : isFinalStep ? activationDisabledReason : undefined
                            }
                            sideIcon={isFinalStep ? undefined : <IconArrowRight />}
                            onClick={() =>
                                isFinalStep ? activate() : goToStep(draft.step === 'signals' ? 'scouts' : 'github')
                            }
                            data-attr="inbox-setup-continue"
                        >
                            {isFinalStep
                                ? 'Activate Self-Driving'
                                : draft.step === 'signals'
                                  ? 'Continue to scouts'
                                  : 'Continue'}
                        </LemonButton>
                    </div>
                </GuidedWizardPanel>
            </div>
        </div>
    )
}
