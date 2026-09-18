import { useActions, useValues } from 'kea'

import { IconBook, IconRefresh, IconSearch, IconSparkles } from '@posthog/icons'
import {
    Button,
    Dot,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill-primitives'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

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
    const wizardUiEnabled = useFeatureFlag('WIZARD_UI_ENABLED')
    const { user } = useValues(userLogic)
    const {
        environment,
        filteredRuns,
        hasRunFilters,
        refreshingRuns,
        runs,
        runsFailed,
        runsInitialLoading,
        runsLastLoadedAt,
        search,
        status,
    } = useValues(wizardRunsLogic)
    const { clearRunFilters, refreshRuns, setEnvironment, setSearch, setStatus } = useActions(wizardRunsLogic)

    const {
        commandCopied,
        connectGitHubUrl,
        createRunError,
        createRunRequestLoading,
        filteredPrograms,
        githubIntegration,
        integrationsLoading,
        isLibraryOpen,
        libraryEnvironment,
        librarySearch,
        programSelectionInvalidated,
        registryFailed,
        registryInitialLoading,
        repository,
        selectedProgram,
        selectedProgramCommand,
        wizardCloudRunAvailable,
    } = useValues(wizardLibraryLogic)
    const {
        closeLibrary,
        copyCommand,
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
        runArtifactsError,
        runDetailsError,
        runDetailsLoading,
        runDiffError,
        runDiffLoading,
        selectedRun,
        selectedRunArtifacts,
        selectedRunArtifactsInitialLoading,
        selectedRunDiffArtifactId,
        selectedRunDiffContent,
    } = useValues(wizardRunDetailsLogic)
    const { cancelRun, closeRunDiff, copyRunId, openRunDiff, refreshSelectedRun, selectRun } =
        useActions(wizardRunDetailsLogic)

    if (!wizardUiEnabled) {
        return <NotFound object="Wizard" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex h-8 items-center gap-2">
                        <span className="flex h-8 items-center" aria-hidden>
                            <IconSparkles className="-translate-y-1 text-ai" />
                        </span>
                        <Text render={<h1 />} size="lg" weight="semibold" className="flex h-8 items-center">
                            Wizard
                        </Text>
                    </div>
                    <Button
                        variant="primary"
                        size="lg"
                        onClick={() => openLibrary()}
                        disabled={!wizardCloudRunAvailable}
                    >
                        <IconBook />
                        Open Wizard Library
                    </Button>
                </div>
                <Text size="sm">Run the setup agent in the cloud, then review the changes it produces.</Text>
            </div>

            <div className="mb-4 flex flex-wrap items-center gap-2">
                <InputGroup className="w-[280px]">
                    <InputGroupInput
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder="Search Wizard runs"
                    />
                    <InputGroupAddon align="inline-start">
                        <IconSearch />
                    </InputGroupAddon>
                </InputGroup>

                <div className="flex-1" />

                {!runsInitialLoading && !runsFailed && filteredRuns.length > 0 && runsLastLoadedAt && (
                    <Text
                        size="xs"
                        className="flex h-8 translate-y-1 items-center gap-1 whitespace-nowrap text-success-foreground leading-[1.625]"
                    >
                        <Dot />
                        Updated {dayjs(runsLastLoadedAt).fromNow()}
                    </Text>
                )}

                <Select value={environment} onValueChange={(value) => value && setEnvironment(value)}>
                    <SelectTrigger className="!h-8 min-w-40" aria-label="Environment">
                        <SelectValue>
                            {environment === 'all' ? 'All environments' : environment === 'cloud' ? 'Cloud' : 'Local'}
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            <SelectItem value="all">All environments</SelectItem>
                            <SelectItem value="cloud">Cloud</SelectItem>
                            <SelectItem value="local">Local</SelectItem>
                        </SelectGroup>
                    </SelectContent>
                </Select>
                <Select value={status} onValueChange={(value) => value && setStatus(value)}>
                    <SelectTrigger className="!h-8 min-w-36" aria-label="Status">
                        <SelectValue>
                            {status === 'all'
                                ? 'All statuses'
                                : status === 'created'
                                  ? 'Starting'
                                  : status === 'cancelled'
                                    ? 'Canceled'
                                    : status[0].toUpperCase() + status.slice(1)}
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            <SelectItem value="all">All statuses</SelectItem>
                            <SelectItem value="created">Starting</SelectItem>
                            <SelectItem value="running">Running</SelectItem>
                            <SelectItem value="completed">Completed</SelectItem>
                            <SelectItem value="failed">Failed</SelectItem>
                            <SelectItem value="cancelled">Canceled</SelectItem>
                        </SelectGroup>
                    </SelectContent>
                </Select>
                <Button variant="outline" size="lg" onClick={refreshRuns} loading={refreshingRuns}>
                    <IconRefresh />
                    Refresh
                </Button>
            </div>

            <WizardRunTable
                runs={filteredRuns}
                totalRuns={runs.length}
                currentUserId={user?.id ?? null}
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
                search={librarySearch}
                command={selectedProgramCommand}
                environment={libraryEnvironment}
                repository={repository}
                githubIntegrationId={githubIntegration?.id ?? null}
                githubConnected={!!githubIntegration && githubIntegration.installation_status !== 'unavailable'}
                githubIntegrationLoading={integrationsLoading}
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
            />

            <WizardRunDetailsDrawer
                run={selectedRun}
                artifacts={selectedRunArtifacts}
                artifactsError={runArtifactsError}
                artifactsLoading={selectedRunArtifactsInitialLoading}
                currentUserId={user?.id ?? null}
                detailsError={runDetailsError}
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
