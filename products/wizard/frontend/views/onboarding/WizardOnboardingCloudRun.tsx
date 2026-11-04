import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconCloud, IconGithub, IconTerminal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { wizardOnboardingCloudRunLogic, type WizardOnboardingCloudRunProps } from './wizardOnboardingCloudRunLogic'

export function WizardOnboardingCloudRun({
    children,
    ...props
}: WizardOnboardingCloudRunProps & { children: ReactNode }): JSX.Element {
    const logic = wizardOnboardingCloudRunLogic(props)
    const {
        mode,
        runActive,
        repository,
        githubIntegration,
        setupLoading,
        setupError,
        startLabel,
        program,
        createRunRequestLoading,
        createError,
        connectGitHubUrl,
    } = useValues(logic)
    const { setMode, setRepository, startCloudRun, retrySetup } = useActions(logic)

    return (
        <div className="flex flex-col gap-4" data-attr="wizard-onboarding-cloud-options">
            <LemonSegmentedButton
                fullWidth
                value={mode}
                onChange={(value) => {
                    if (value !== mode) {
                        setMode(value)
                    }
                }}
                options={[
                    {
                        value: 'cloud',
                        label: 'Open a pull request',
                        icon: <IconCloud />,
                        'data-attr': 'wizard-mode-cloud',
                    },
                    {
                        value: 'local',
                        label: 'Run it yourself',
                        icon: <IconTerminal />,
                        'data-attr': 'wizard-mode-local',
                    },
                ]}
            />
            {mode === 'local' ? (
                children
            ) : (
                <div className="flex flex-col gap-4" data-attr="wizard-cloud-run-block">
                    <p className="text-sm text-muted mb-0">
                        The setup agent runs in the cloud and opens a pull request. Review and merge the changes when
                        you are ready.
                    </p>
                    {runActive ? (
                        <LemonBanner type="info">
                            A setup run is in progress. You can continue onboarding and review its results here.
                        </LemonBanner>
                    ) : setupLoading ? (
                        <Spinner />
                    ) : setupError ? (
                        <LemonBanner type="error" action={{ children: 'Retry', onClick: () => retrySetup() }}>
                            {setupError}
                        </LemonBanner>
                    ) : !program ? (
                        <LemonBanner type="warning">
                            Cloud setup is not available. Select Run it yourself to use the local command.
                        </LemonBanner>
                    ) : !githubIntegration ? (
                        <LemonButton
                            type="secondary"
                            icon={<IconGithub />}
                            to={connectGitHubUrl}
                            disableClientSideRouting
                            data-attr="wizard-cloud-run-connect-github"
                            className="self-start"
                        >
                            Connect GitHub
                        </LemonButton>
                    ) : (
                        <>
                            <div className="flex flex-col gap-2">
                                <LemonLabel>GitHub repository</LemonLabel>
                                <GitHubRepositoryPicker
                                    integrationId={githubIntegration.id}
                                    value={repository}
                                    onChange={setRepository}
                                    valueKey="full_name"
                                />
                            </div>
                            {createError && <LemonBanner type="error">{createError}</LemonBanner>}
                            <LemonButton
                                type="primary"
                                onClick={() => startCloudRun()}
                                loading={createRunRequestLoading}
                                disabledReason={!repository ? 'Select a repository first' : undefined}
                                data-attr="wizard-cloud-run-open-pr"
                                className="self-start"
                            >
                                {startLabel}
                            </LemonButton>
                        </>
                    )}
                </div>
            )}
        </div>
    )
}
