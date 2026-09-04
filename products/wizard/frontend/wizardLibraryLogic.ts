import { MakeLogicType, actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiError } from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import type { IntegrationType } from '../../../frontend/src/types'
import { wizardRegistryList, wizardRunsCreate } from './generated/api'
import type {
    RunEnvironmentEnumApi,
    WizardProgramApi,
    WizardRunApi,
    WizardRunCreateRequestApi,
} from './generated/api.schemas'
import { WIZARD_LOCAL_RUNS_VISIBLE, wizardCommand } from './wizardRunDisplay'
import { wizardRunsLogic } from './wizardRunsLogic'

function requestError(error: unknown, fallback: string): string {
    return error instanceof ApiError && error.detail ? error.detail : fallback
}

export interface wizardLibraryLogicValues {
    currentProjectId: number | null
    githubIntegrations: IntegrationType[]
    githubRepositoriesByIntegration: Record<number, GitHubRepoApi[]>
    githubRepositoriesLoading: boolean
    integrationsLoading: boolean
    availableRepositories: GitHubRepoApi[]
    commandCopied: boolean
    connectGitHubUrl: string
    createRunError: string | null
    createRunIdempotencyKey: string | null
    createRunRequest: WizardRunApi | null
    createRunRequestLoading: boolean
    filteredPrograms: WizardProgramApi[]
    githubIntegration: IntegrationType | null
    isLibraryOpen: boolean
    libraryEnvironment: RunEnvironmentEnumApi
    librarySearch: string
    programSelectionInvalidated: boolean
    registry: WizardProgramApi[]
    registryFailed: boolean
    registryInitialLoading: boolean
    registryLoading: boolean
    repository: string
    requiredPrograms: WizardProgramApi[]
    selectedProgram: WizardProgramApi | null
    selectedProgramCommand: string
}

export interface wizardLibraryLogicActions {
    closeLibrary: () => { value: true }
    copyCommand: () => { value: true }
    createRun: () => { value: true }
    createRunRequest: ({ projectId, body }: { projectId: string; body: WizardRunCreateRequestApi }) => {
        projectId: string
        body: WizardRunCreateRequestApi
    }
    createRunRequestFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    createRunRequestSuccess: (
        createRunRequest: WizardRunApi,
        payload?: { projectId: string; body: WizardRunCreateRequestApi }
    ) => {
        createRunRequest: WizardRunApi
        payload?: { projectId: string; body: WizardRunCreateRequestApi }
    }
    invalidateProgramSelection: () => { value: true }
    loadGitHubRepositories: (integrationId: number) => { integrationId: number }
    loadIntegrations: () => { value: true }
    loadIntegrationsSuccess: (integrations: IntegrationType[]) => { integrations: IntegrationType[] }
    loadRegistry: () => { value: true }
    loadRegistryFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadRegistrySuccess: (registry: WizardProgramApi[]) => { registry: WizardProgramApi[] }
    markCommandCopied: () => { value: true }
    openLibrary: (idempotencyKey?: string) => { idempotencyKey: string }
    refreshRuns: () => { value: true }
    runAgain: (run: WizardRunApi) => { run: WizardRunApi }
    selectProgram: (program: WizardProgramApi) => { program: WizardProgramApi }
    setLibraryEnvironment: (environment: RunEnvironmentEnumApi) => { environment: RunEnvironmentEnumApi }
    setLibrarySearch: (search: string) => { search: string }
    setRepository: (repository: string) => { repository: string }
}

export interface wizardLibraryLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        availableRepositories: (
            githubIntegration: IntegrationType | null,
            githubRepositoriesByIntegration: Record<number, GitHubRepoApi[]>
        ) => GitHubRepoApi[]
        connectGitHubUrl: () => string
        filteredPrograms: (registry: WizardProgramApi[], librarySearch: string) => WizardProgramApi[]
        githubIntegration: (githubIntegrations: IntegrationType[]) => IntegrationType | null
        registryInitialLoading: (registryLoading: boolean, registry: WizardProgramApi[]) => boolean
        requiredPrograms: (selectedProgram: WizardProgramApi | null, registry: WizardProgramApi[]) => WizardProgramApi[]
        selectedProgramCommand: (selectedProgram: WizardProgramApi | null) => string
    }
}

export type wizardLibraryLogicType = MakeLogicType<
    wizardLibraryLogicValues,
    wizardLibraryLogicActions,
    Record<string, never>,
    wizardLibraryLogicMeta
>

export const wizardLibraryLogic = kea<wizardLibraryLogicType>([
    path(['products', 'wizard', 'wizardLibraryLogic']),
    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            integrationsLogic,
            [
                'githubIntegrations',
                'githubRepositories as githubRepositoriesByIntegration',
                'githubRepositoriesLoading',
                'integrationsLoading',
            ],
        ],
        actions: [
            integrationsLogic,
            ['loadGitHubRepositories', 'loadIntegrations', 'loadIntegrationsSuccess'],
            wizardRunsLogic,
            ['refreshRuns'],
        ],
    })),
    actions({
        openLibrary: (idempotencyKey = crypto.randomUUID()) => ({ idempotencyKey }),
        closeLibrary: true,
        setLibrarySearch: (search: string) => ({ search }),
        selectProgram: (program: WizardProgramApi) => ({ program }),
        invalidateProgramSelection: true,
        setLibraryEnvironment: (environment: RunEnvironmentEnumApi) => ({ environment }),
        setRepository: (repository: string) => ({ repository }),
        copyCommand: true,
        markCommandCopied: true,
        runAgain: (run: WizardRunApi) => ({ run }),
        createRun: true,
    }),
    reducers({
        isLibraryOpen: [false, { openLibrary: () => true, closeLibrary: () => false }],
        createRunIdempotencyKey: [
            null as string | null,
            {
                openLibrary: (_, { idempotencyKey }) => idempotencyKey,
                closeLibrary: () => null,
            },
        ],
        librarySearch: ['', { setLibrarySearch: (_, { search }) => search, openLibrary: () => '' }],
        selectedProgram: [
            null as WizardProgramApi | null,
            {
                selectProgram: (_, { program }) => program,
                invalidateProgramSelection: () => null,
            },
        ],
        programSelectionInvalidated: [
            false,
            {
                selectProgram: () => false,
                invalidateProgramSelection: () => true,
                closeLibrary: () => false,
            },
        ],
        libraryEnvironment: [
            'cloud' as RunEnvironmentEnumApi,
            { setLibraryEnvironment: (_, { environment }) => environment },
        ],
        repository: ['', { setRepository: (_, { repository }) => repository, closeLibrary: () => '' }],
        commandCopied: [
            false,
            {
                markCommandCopied: () => true,
                selectProgram: () => false,
                closeLibrary: () => false,
            },
        ],
        registryFailed: [false, { loadRegistry: () => false, loadRegistryFailure: () => true }],
        createRunError: [
            null as string | null,
            {
                createRun: () => null,
                setRepository: () => null,
                closeLibrary: () => null,
                createRunRequestFailure: (_, { errorObject }) =>
                    requestError(errorObject, "Couldn't start the cloud run. Check the repository and try again."),
            },
        ],
    }),
    loaders(({ values }) => ({
        registry: [
            [] as WizardProgramApi[],
            {
                loadRegistry: async () => {
                    if (!values.currentProjectId) {
                        return []
                    }

                    const response = await wizardRegistryList(String(values.currentProjectId), {
                        limit: 100,
                        offset: 0,
                    })

                    return response.results
                },
            },
        ],
        createRunRequest: [
            null as WizardRunApi | null,
            {
                createRunRequest: async ({ projectId, body }: { projectId: string; body: WizardRunCreateRequestApi }) =>
                    wizardRunsCreate(projectId, body),
            },
        ],
    })),
    selectors({
        filteredPrograms: [
            (s) => [s.registry, s.librarySearch],
            (programs: WizardProgramApi[], search: string): WizardProgramApi[] => {
                const availablePrograms = WIZARD_LOCAL_RUNS_VISIBLE
                    ? programs
                    : programs.filter((program) => program.supported_environments.includes('cloud'))
                const searchText = search.trim().toLowerCase()

                if (!searchText) {
                    return availablePrograms
                }

                return availablePrograms.filter((program) =>
                    `${program.name} ${program.description} ${program.tags.join(' ')}`
                        .toLowerCase()
                        .includes(searchText)
                )
            },
        ],
        githubIntegration: [
            (s) => [s.githubIntegrations],
            (githubIntegrations: IntegrationType[]): IntegrationType | null => githubIntegrations[0] ?? null,
        ],
        availableRepositories: [
            (s) => [s.githubIntegration, s.githubRepositoriesByIntegration],
            (
                githubIntegration: IntegrationType | null,
                githubRepositoriesByIntegration: Record<number, GitHubRepoApi[]>
            ): GitHubRepoApi[] =>
                githubIntegration ? (githubRepositoriesByIntegration[githubIntegration.id] ?? []) : [],
        ],
        connectGitHubUrl: [
            () => [],
            (): string => api.integrations.authorizeUrl({ kind: 'github', next: urls.wizardRuns() }),
        ],
        selectedProgramCommand: [
            (s) => [s.selectedProgram],
            (program: WizardProgramApi | null): string =>
                program ? wizardCommand(program.wizard_version, program.command) : '',
        ],
        requiredPrograms: [
            (s) => [s.selectedProgram, s.registry],
            (program: WizardProgramApi | null, registry: WizardProgramApi[]): WizardProgramApi[] =>
                program
                    ? program.required_programs
                          .map((requiredId) => registry.find((candidate) => candidate.id === requiredId))
                          .filter((candidate): candidate is WizardProgramApi => !!candidate)
                    : [],
        ],
        registryInitialLoading: [
            (s) => [s.registryLoading, s.registry],
            (registryLoading: boolean, registry: WizardProgramApi[]): boolean =>
                registryLoading && registry.length === 0,
        ],
    }),
    listeners(({ actions, values }) => ({
        openLibrary: () => {
            actions.loadRegistry()
            actions.loadIntegrations()

            if (!WIZARD_LOCAL_RUNS_VISIBLE) {
                actions.setLibraryEnvironment('cloud')
            }

            if (values.githubIntegration) {
                actions.loadGitHubRepositories(values.githubIntegration.id)
            }

            if (!values.selectedProgram && values.filteredPrograms.length > 0) {
                actions.selectProgram(values.filteredPrograms[0])
            }
        },
        loadIntegrationsSuccess: ({ integrations }) => {
            const githubIntegration = integrations.find((integration) => integration.kind === 'github')

            if (githubIntegration) {
                actions.loadGitHubRepositories(githubIntegration.id)
            }
        },
        selectProgram: ({ program }) => {
            const environment =
                WIZARD_LOCAL_RUNS_VISIBLE && !program.supported_environments.includes('cloud') ? 'local' : 'cloud'

            actions.setLibraryEnvironment(environment)
        },
        copyCommand: () => {
            if (values.selectedProgramCommand) {
                void copyToClipboard(values.selectedProgramCommand, 'Wizard command').then((copied) => {
                    if (copied) {
                        actions.markCommandCopied()
                    }
                })
            }
        },
        runAgain: ({ run }) => {
            if (!WIZARD_LOCAL_RUNS_VISIBLE && run.environment === 'local') {
                return
            }

            const currentProgram = values.registry.find((program) => program.id === run.program.id)

            if (currentProgram) {
                actions.selectProgram(currentProgram)
            }

            actions.setLibraryEnvironment(run.environment)

            if (run.workspace.type === 'git_repository') {
                actions.setRepository(run.workspace.repository)
            }

            actions.openLibrary()
        },
        createRun: () => {
            const projectId = values.currentProjectId
            const program = values.selectedProgram

            if (!projectId || !program || values.libraryEnvironment !== 'cloud' || !values.createRunIdempotencyKey) {
                return
            }

            const workspace: WizardRunCreateRequestApi['workspace'] = {
                type: 'git_repository',
                repository: values.repository,
            }

            actions.createRunRequest({
                projectId: String(projectId),
                body: {
                    program_id: program.id,
                    environment: values.libraryEnvironment,
                    workspace,
                    idempotency_key: values.createRunIdempotencyKey,
                },
            })
        },
        createRunRequestSuccess: () => {
            lemonToast.success('Cloud run started.')
            actions.closeLibrary()
            actions.refreshRuns()
        },
        loadRegistrySuccess: ({ registry }) => {
            const availablePrograms = WIZARD_LOCAL_RUNS_VISIBLE
                ? registry
                : registry.filter((program) => program.supported_environments.includes('cloud'))

            if (
                values.selectedProgram &&
                !availablePrograms.some((program) => program.id === values.selectedProgram?.id)
            ) {
                actions.invalidateProgramSelection()
            } else if (!values.selectedProgram && availablePrograms.length > 0) {
                actions.selectProgram(availablePrograms[0])
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadRegistry()
            actions.loadIntegrations()
        },
    })),
])
