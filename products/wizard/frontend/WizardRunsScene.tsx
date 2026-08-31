import { useActions, useValues } from 'kea'

import { IconBook, IconRefresh, IconSearch, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { WizardLibraryModal } from './library/WizardLibraryModal'
import { WizardRunDetailsDrawer } from './runs/WizardRunDetailsDrawer'
import { WizardRunTable } from './runs/WizardRunTable'
import { wizardLibraryLogic } from './wizardLibraryLogic'
import { wizardRunDetailsLogic } from './wizardRunDetailsLogic'
import { wizardRunsLogic } from './wizardRunsLogic'

export const scene: SceneExport = {
    component: WizardRunsScene,
    logic: wizardRunsLogic,
}

export function WizardRunsScene(): JSX.Element {
    const { environment, filteredRuns, hasRunFilters, refreshingRuns, runsFailed, runsInitialLoading, search, status } =
        useValues(wizardRunsLogic)
    const { clearRunFilters, refreshRuns, setEnvironment, setSearch, setStatus } = useActions(wizardRunsLogic)

    const {
        availableRepositories,
        commandCopied,
        connectGitHubUrl,
        createRunError,
        createRunRequestLoading,
        filteredPrograms,
        githubIntegration,
        githubRepositoriesLoading,
        integrationsLoading,
        isLibraryOpen,
        libraryEnvironment,
        librarySearch,
        programSelectionInvalidated,
        registryFailed,
        registryInitialLoading,
        repository,
        requiredPrograms,
        selectedProgram,
        selectedProgramCommand,
    } = useValues(wizardLibraryLogic)
    const {
        closeLibrary,
        copyCommand,
        markCommandCopied,
        createRun,
        openLibrary,
        runAgain,
        selectProgram,
        setLibraryEnvironment,
        setLibrarySearch,
        setRepository,
    } = useActions(wizardLibraryLogic)

    const {
        cancelRunRequestLoading,
        runDetailsLoading,
        runDiffError,
        runDiffLoading,
        selectedRun,
        selectedRunArtifacts,
        selectedRunArtifactsInitialLoading,
        selectedRunDiffArtifactId,
        selectedRunDiffContent,
        selectedRunId,
    } = useValues(wizardRunDetailsLogic)
    const { cancelRun, closeRunDiff, copyRunId, openRunDiff, refreshSelectedRun, selectRun } =
        useActions(wizardRunDetailsLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Wizard"
                description="Run the setup agent locally or in the cloud, then review the changes it produces."
                descriptionAlwaysVisible
                hideProductSetupButton
                resourceType={{ type: 'default_icon_type', forceIcon: <IconSparkles className="text-ai" /> }}
                actions={
                    <LemonButton type="primary" icon={<IconBook />} onClick={() => openLibrary()}>
                        Open Wizard Library
                    </LemonButton>
                }
            />

            <div className="mb-4 flex flex-wrap items-center gap-2">
                <LemonInput
                    value={search}
                    onChange={setSearch}
                    prefix={<IconSearch />}
                    placeholder="Search Wizard runs"
                    className="w-[280px]"
                />

                <div className="flex-1" />

                {!runsInitialLoading && filteredRuns.length > 0 && (
                    <span className="flex items-center gap-1 whitespace-nowrap text-xs text-success">
                        <span className="size-2 rounded-full bg-success" /> Live updates · Just now
                    </span>
                )}

                <LemonSelect
                    className="min-w-40"
                    value={environment}
                    onChange={setEnvironment}
                    options={[
                        { value: 'all', label: 'All environments' },
                        { value: 'cloud', label: 'Cloud' },
                        { value: 'local', label: 'Local' },
                    ]}
                />
                <LemonSelect
                    className="min-w-36"
                    value={status}
                    onChange={setStatus}
                    options={[
                        { value: 'all', label: 'All statuses' },
                        { value: 'created', label: 'Starting' },
                        { value: 'running', label: 'Running' },
                        { value: 'completed', label: 'Completed' },
                        { value: 'failed', label: 'Failed' },
                        { value: 'cancelled', label: 'Canceled' },
                    ]}
                />
                <LemonButton icon={<IconRefresh />} onClick={refreshRuns} loading={refreshingRuns}>
                    Refresh
                </LemonButton>
            </div>

            <WizardRunTable
                runs={filteredRuns}
                selectedRunId={selectedRunId}
                loading={runsInitialLoading}
                failed={runsFailed}
                hasActiveFilters={hasRunFilters}
                refreshing={refreshingRuns}
                cancelling={cancelRunRequestLoading}
                onOpenLibrary={openLibrary}
                onClearFilters={clearRunFilters}
                onRefreshRuns={refreshRuns}
                onSelect={selectRun}
                onRefreshRun={refreshRuns}
                onCopyRunId={copyRunId}
                onCancel={cancelRun}
            />

            <WizardLibraryModal
                isOpen={isLibraryOpen}
                filteredPrograms={filteredPrograms}
                loading={registryInitialLoading}
                failed={registryFailed}
                selectedProgram={selectedProgram}
                requiredPrograms={requiredPrograms}
                search={librarySearch}
                command={selectedProgramCommand}
                environment={libraryEnvironment}
                repository={repository}
                repositories={availableRepositories}
                githubConnected={!!githubIntegration}
                githubIntegrationLoading={integrationsLoading}
                githubRepositoriesLoading={githubRepositoriesLoading}
                connectGitHubUrl={connectGitHubUrl}
                creating={createRunRequestLoading}
                createError={createRunError}
                commandCopied={commandCopied}
                selectionInvalidated={programSelectionInvalidated}
                onClose={closeLibrary}
                onSearch={setLibrarySearch}
                onSelect={selectProgram}
                onEnvironmentChange={setLibraryEnvironment}
                onRepositoryChange={setRepository}
                onCreate={createRun}
                onCopyCommand={copyCommand}
                onCommandCopied={markCommandCopied}
            />

            <WizardRunDetailsDrawer
                run={selectedRun}
                artifacts={selectedRunArtifacts}
                artifactsLoading={selectedRunArtifactsInitialLoading}
                refreshing={runDetailsLoading}
                cancelling={cancelRunRequestLoading}
                diffArtifactId={selectedRunDiffArtifactId}
                diffContent={selectedRunDiffContent}
                diffError={runDiffError}
                diffLoading={runDiffLoading}
                onClose={() => selectRun(null)}
                onCloseDiff={closeRunDiff}
                onOpenDiff={openRunDiff}
                onRefresh={refreshSelectedRun}
                onCopyRunId={copyRunId}
                onCancel={cancelRun}
                onRunAgain={runAgain}
            />
        </SceneContent>
    )
}
