import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import type { WizardRunApi, WizardRunArtifactApi, WizardRunTaskApi } from '../../generated/api.schemas'
import { wizardRunIsActive } from '../../lib/wizardRunDisplay'
import type { WizardSpendAuditView } from './wizardSpendAuditLogic'
import { WizardSpendAuditRunView } from './WizardSpendAuditRunView'

export interface WizardSpendAuditModalViewProps {
    isOpen: boolean
    view: WizardSpendAuditView
    repository: string
    githubIntegrationId: number | null
    connectGitHubUrl: string
    setupError: string | null
    creating: boolean
    createError: string | null
    run: WizardRunApi | null
    tasks: readonly WizardRunTaskApi[]
    artifacts: readonly WizardRunArtifactApi[]
    runDataLoading: boolean
    runDataError: string | null
    now: number
    onClose: () => void
    onRepositoryChange: (repository: string) => void
    onStart: () => void
    onRetrySetup: () => void
    onRunAgain: () => void
    onRetryRunData: () => void
}

export function WizardSpendAuditModalView({
    isOpen,
    view,
    repository,
    githubIntegrationId,
    connectGitHubUrl,
    setupError,
    creating,
    createError,
    run,
    tasks,
    artifacts,
    runDataLoading,
    runDataError,
    now,
    onClose,
    onRepositoryChange,
    onStart,
    onRetrySetup,
    onRunAgain,
    onRetryRunData,
}: WizardSpendAuditModalViewProps): JSX.Element {
    const runFinished = !!run && !wizardRunIsActive(run)

    let body: JSX.Element
    let footer: JSX.Element | null = null

    switch (view) {
        case 'loading':
            body = (
                <div className="flex items-center gap-2 text-muted">
                    <Spinner />
                    <span>Checking your GitHub connection…</span>
                </div>
            )
            break
        case 'error':
            body = (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: onRetrySetup }}>
                    {setupError}
                </LemonBanner>
            )
            break
        case 'unavailable':
            body = (
                <LemonBanner type="warning">
                    The spend audit is not available for this project yet. Check back soon.
                </LemonBanner>
            )
            break
        case 'connect_github':
            body = (
                <div className="flex flex-col gap-4">
                    <p className="mb-0">
                        Connect GitHub so the agent can read your code. The audit starts as soon as you are back.
                    </p>
                    <LemonButton
                        type="primary"
                        icon={<IconGithub />}
                        to={connectGitHubUrl}
                        disableClientSideRouting
                        data-attr="wizard-spend-audit-connect-github"
                        className="self-start"
                    >
                        Connect GitHub
                    </LemonButton>
                </div>
            )
            break
        case 'pick_repository':
            body = (
                <div className="flex flex-col gap-4">
                    <div className="flex flex-col gap-2">
                        <LemonLabel>GitHub repository</LemonLabel>
                        {githubIntegrationId === null ? (
                            <Spinner />
                        ) : (
                            <GitHubRepositoryPicker
                                integrationId={githubIntegrationId}
                                value={repository}
                                onChange={onRepositoryChange}
                                valueKey="full_name"
                            />
                        )}
                        <p className="mb-0 text-xs text-muted">
                            Pick the repository that sends data to PostHog. The agent opens a pull request there.
                        </p>
                    </div>
                    {createError && <LemonBanner type="error">{createError}</LemonBanner>}
                </div>
            )
            footer = (
                <LemonButton
                    type="primary"
                    onClick={onStart}
                    loading={creating}
                    disabledReason={!repository ? 'Select a repository first' : undefined}
                    data-attr="wizard-spend-audit-start"
                >
                    Start audit
                </LemonButton>
            )
            break
        case 'run':
            body = run ? (
                <WizardSpendAuditRunView
                    run={run}
                    tasks={tasks}
                    artifacts={artifacts}
                    now={now}
                    loading={runDataLoading}
                    error={runDataError}
                    onRetry={onRetryRunData}
                />
            ) : (
                <div className="flex items-center gap-2 text-muted">
                    <Spinner />
                    <span>Starting the audit…</span>
                </div>
            )
            footer = (
                <>
                    {runFinished && (
                        <LemonButton type="secondary" onClick={onRunAgain} data-attr="wizard-spend-audit-run-again">
                            Run again
                        </LemonButton>
                    )}
                    <LemonButton type="primary" onClick={onClose} data-attr="wizard-spend-audit-done">
                        {runFinished ? 'Done' : 'Close'}
                    </LemonButton>
                </>
            )
            break
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Optimize my spend"
            description="The setup agent audits how your code sends data to PostHog, opens a pull request with the code changes that lower your bill, and writes a notebook with the settings to change."
            footer={footer}
            width={560}
            data-attr="wizard-spend-audit-modal"
        >
            {body}
        </LemonModal>
    )
}
