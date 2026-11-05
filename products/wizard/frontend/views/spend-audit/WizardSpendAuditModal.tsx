import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'

import { type WizardSpendAuditLogicProps, wizardSpendAuditLogic } from './wizardSpendAuditLogic'
import { WizardSpendAuditModalView } from './WizardSpendAuditModalView'

export function WizardSpendAuditModal(props: WizardSpendAuditLogicProps): JSX.Element {
    const logic = wizardSpendAuditLogic(props)
    const {
        isModalOpen,
        view,
        repository,
        githubIntegration,
        connectGitHubUrl,
        setupError,
        createRunRequestLoading,
        createError,
        run,
        runActive,
        runTasks,
        runArtifacts,
        runDataIsLoading,
        runDataError,
        accountOwner,
        currentOrganization,
    } = useValues(logic)
    const { closeModal, setRepository, startAudit, retrySetup, runAgain, loadRunData } = useActions(logic)
    const [now, setNow] = useState(Date.now)
    useInterval(() => setNow(Date.now()), isModalOpen && runActive ? 1000 : null)

    return (
        <WizardSpendAuditModalView
            isOpen={isModalOpen}
            view={view}
            repository={repository}
            githubIntegrationId={githubIntegration?.id ?? null}
            connectGitHubUrl={connectGitHubUrl}
            setupError={setupError}
            creating={createRunRequestLoading}
            createError={createError}
            run={run}
            tasks={runTasks}
            artifacts={runArtifacts}
            runDataLoading={runDataIsLoading}
            runDataError={runDataError}
            accountOwner={accountOwner}
            organizationName={currentOrganization?.name ?? null}
            now={now}
            onClose={closeModal}
            onRepositoryChange={setRepository}
            onStart={startAudit}
            onRetrySetup={retrySetup}
            onRunAgain={runAgain}
            onRetryRunData={() => run && loadRunData(run, { force: true })}
        />
    )
}
