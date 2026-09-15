import {
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@posthog/quill-primitives'

import type { RunEnvironmentEnumApi, WizardProgramApi } from '../generated/api.schemas'
import { WizardProgramDetails } from './WizardProgramDetails'
import { WizardProgramList } from './WizardProgramList'

export function WizardLibraryModal({
    isOpen,
    filteredPrograms,
    loading,
    failed,
    selectedProgram,
    search,
    command,
    environment,
    repository,
    githubIntegrationId,
    githubConnected,
    githubIntegrationLoading,
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
}: {
    isOpen: boolean
    filteredPrograms: WizardProgramApi[]
    loading: boolean
    failed: boolean
    selectedProgram: WizardProgramApi | null
    search: string
    command: string
    environment: RunEnvironmentEnumApi
    repository: string
    githubIntegrationId: number | null
    githubConnected: boolean
    githubIntegrationLoading: boolean
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
}): JSX.Element {
    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent size="wide" className="max-w-[1000px]">
                <DialogHeader>
                    <DialogTitle>Wizard Library</DialogTitle>
                    <DialogDescription>Choose what you want the setup agent to do.</DialogDescription>
                </DialogHeader>
                <DialogBody viewportClassName="p-0">
                    <div className="@container">
                        <div className="flex h-[min(680px,78vh)] min-h-0 flex-col @3xl:flex-row">
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
                                loading={loading}
                                program={selectedProgram}
                                command={command}
                                environment={environment}
                                repository={repository}
                                githubIntegrationId={githubIntegrationId}
                                githubConnected={githubConnected}
                                githubIntegrationLoading={githubIntegrationLoading}
                                connectGitHubUrl={connectGitHubUrl}
                                creating={creating}
                                createError={createError}
                                commandCopied={commandCopied}
                                selectionInvalidated={selectionInvalidated}
                                onEnvironmentChange={onEnvironmentChange}
                                onRepositoryChange={onRepositoryChange}
                                onCreate={onCreate}
                                onCopyCommand={onCopyCommand}
                            />
                        </div>
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
