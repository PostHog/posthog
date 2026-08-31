import { LemonModal } from '@posthog/lemon-ui'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import type { RunEnvironmentEnumApi, WizardProgramApi } from '../generated/api.schemas'
import { WizardProgramDetails } from './WizardProgramDetails'
import { WizardProgramList } from './WizardProgramList'

export function WizardLibraryModal({
    isOpen,
    filteredPrograms,
    loading,
    failed,
    selectedProgram,
    requiredPrograms,
    search,
    command,
    environment,
    repository,
    repositories,
    githubConnected,
    githubIntegrationLoading,
    githubRepositoriesLoading,
    connectGitHubUrl,
    creating,
    createError,
    commandCopied,
    selectionInvalidated,
    onClose,
    onSearch,
    onSelect,
    onEnvironmentChange,
    onRepositoryChange,
    onCreate,
    onCopyCommand,
    onCommandCopied,
}: {
    isOpen: boolean
    filteredPrograms: WizardProgramApi[]
    loading: boolean
    failed: boolean
    selectedProgram: WizardProgramApi | null
    requiredPrograms: WizardProgramApi[]
    search: string
    command: string
    environment: RunEnvironmentEnumApi
    repository: string
    repositories: GitHubRepoApi[]
    githubConnected: boolean
    githubIntegrationLoading: boolean
    githubRepositoriesLoading: boolean
    connectGitHubUrl: string
    creating: boolean
    createError: string | null
    commandCopied: boolean
    selectionInvalidated: boolean
    onClose: () => void
    onSearch: (search: string) => void
    onSelect: (program: WizardProgramApi) => void
    onEnvironmentChange: (environment: RunEnvironmentEnumApi) => void
    onRepositoryChange: (repository: string) => void
    onCreate: () => void
    onCopyCommand: () => void
    onCommandCopied: () => void
}): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Wizard Library"
            description="Choose what you want the setup agent to do."
            width={1000}
            maxWidth="95vw"
        >
            <div className="flex h-[min(680px,75vh)] min-h-0 flex-col gap-5 lg:flex-row">
                <WizardProgramList
                    programs={filteredPrograms}
                    selectedProgram={selectedProgram}
                    search={search}
                    loading={loading}
                    failed={failed}
                    onSearch={onSearch}
                    onSelect={onSelect}
                />
                <WizardProgramDetails
                    program={selectedProgram}
                    requiredPrograms={requiredPrograms}
                    command={command}
                    environment={environment}
                    repository={repository}
                    repositories={repositories}
                    githubConnected={githubConnected}
                    githubIntegrationLoading={githubIntegrationLoading}
                    githubRepositoriesLoading={githubRepositoriesLoading}
                    connectGitHubUrl={connectGitHubUrl}
                    creating={creating}
                    createError={createError}
                    commandCopied={commandCopied}
                    selectionInvalidated={selectionInvalidated}
                    onEnvironmentChange={onEnvironmentChange}
                    onRepositoryChange={onRepositoryChange}
                    onCreate={onCreate}
                    onCopyCommand={onCopyCommand}
                    onCommandCopied={onCommandCopied}
                />
            </div>
        </LemonModal>
    )
}
