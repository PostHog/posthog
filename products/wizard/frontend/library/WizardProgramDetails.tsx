import { IconCloud, IconGithub, IconLaptop } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonInputSelect, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import type { RunEnvironmentEnumApi, WizardProgramApi } from '../generated/api.schemas'
import { WIZARD_LOCAL_RUNS_VISIBLE } from '../wizardRunDisplay'
import { WizardCommand } from './WizardCommand'

export function WizardProgramDetails({
    program,
    requiredPrograms,
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
    onEnvironmentChange,
    onRepositoryChange,
    onCreate,
    onCopyCommand,
    onCommandCopied,
}: {
    program: WizardProgramApi | null
    requiredPrograms: WizardProgramApi[]
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
    onEnvironmentChange: (environment: RunEnvironmentEnumApi) => void
    onRepositoryChange: (repository: string) => void
    onCreate: () => void
    onCopyCommand: () => void
    onCommandCopied: () => void
}): JSX.Element {
    if (selectionInvalidated) {
        return (
            <LemonBanner type="warning">
                <div className="font-semibold">This program is no longer available.</div>
                <div className="text-sm">Refresh the Library and choose another program.</div>
            </LemonBanner>
        )
    }

    if (!program) {
        return <div className="flex h-full items-center justify-center text-sm text-muted">Select a program.</div>
    }

    const supportsCloud = program.supported_environments.includes('cloud')
    const supportsLocal = program.supported_environments.includes('local')

    return (
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-1 lg:pl-3">
            <div>
                <h3 className="mb-1 text-xl">{program.name}</h3>
                <p className="m-0 text-sm text-muted">{program.description}</p>
            </div>

            <div className="mt-3">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold uppercase text-muted">Supported</span>
                    {supportsCloud && (
                        <LemonTag type="info" size="small" icon={<IconCloud />}>
                            Cloud
                        </LemonTag>
                    )}
                    {WIZARD_LOCAL_RUNS_VISIBLE && supportsLocal && (
                        <LemonTag size="small" icon={<IconLaptop />}>
                            Local
                        </LemonTag>
                    )}
                </div>
                <div className="mt-3 text-sm text-muted">Runs with Wizard {program.wizard_version}</div>
            </div>

            {requiredPrograms.length > 0 && (
                <div className="mt-5 rounded border border-info bg-info-highlight p-3">
                    <div className="text-xs font-semibold uppercase text-muted">Run first</div>
                    {requiredPrograms.map((requiredProgram) => (
                        <div key={requiredProgram.id} className="mt-1 font-semibold underline">
                            {requiredProgram.name}
                        </div>
                    ))}
                </div>
            )}

            {environment === 'cloud' && githubConnected && (
                <div className="mt-3">
                    <WizardCommand
                        command={command}
                        showCopyButton={false}
                        copied={commandCopied}
                        onCopy={onCopyCommand}
                        onCopied={onCommandCopied}
                    />
                </div>
            )}

            <LemonDivider className="my-5" />

            <LemonTabs
                activeKey={environment}
                onChange={onEnvironmentChange}
                tabs={[
                    supportsCloud && {
                        key: 'cloud',
                        label: (
                            <span className="flex items-center gap-1.5">
                                <span>Cloud</span>
                                <span className="text-xs font-normal text-muted">Recommended</span>
                            </span>
                        ),
                    },
                    WIZARD_LOCAL_RUNS_VISIBLE && supportsLocal && { key: 'local', label: 'Local' },
                ]}
            />

            <div className="mt-5">
                {environment === 'cloud' ? (
                    githubIntegrationLoading ? (
                        <div className="text-sm text-muted">Checking the GitHub integration…</div>
                    ) : githubConnected ? (
                        <div className="space-y-3">
                            <div>
                                <label className="mb-1 block text-sm font-semibold">GitHub repository</label>
                                <LemonInputSelect
                                    value={repository ? [repository] : []}
                                    onChange={(values) => onRepositoryChange(values[0] ?? '')}
                                    mode="single"
                                    placeholder="Select a repository"
                                    options={repositories.map((availableRepository) => ({
                                        key: availableRepository.full_name,
                                        label: availableRepository.full_name,
                                    }))}
                                    loading={githubRepositoriesLoading}
                                    fullWidth
                                    disabledReason={creating ? 'A cloud run is starting.' : undefined}
                                    data-attr="wizard-cloud-repository"
                                />
                                <div className="mt-1 text-xs text-muted">
                                    <IconGithub className="mr-1 inline" />
                                    Choose a repository available to the connected GitHub integration.
                                </div>
                            </div>

                            {createError && <LemonBanner type="error">{createError}</LemonBanner>}

                            <LemonButton
                                type="primary"
                                onClick={() => onCreate()}
                                loading={creating}
                                disabledReason={repository ? undefined : 'Select a GitHub repository.'}
                            >
                                Start cloud run
                            </LemonButton>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            <LemonBanner type="warning">
                                <div className="space-y-3">
                                    <div className="font-semibold">
                                        Connect GitHub to run this program in the cloud.
                                    </div>
                                    <div className="flex">
                                        <LemonButton type="secondary" to={connectGitHubUrl} disableClientSideRouting>
                                            Connect GitHub
                                        </LemonButton>
                                    </div>
                                </div>
                            </LemonBanner>

                            {WIZARD_LOCAL_RUNS_VISIBLE && (
                                <div>
                                    <div className="mb-2 text-xs font-semibold uppercase text-muted">Local command</div>
                                    <p className="text-sm">You can still run this program from your project folder.</p>
                                    <WizardCommand
                                        command={command}
                                        showCopyButton={false}
                                        copied={commandCopied}
                                        onCopy={onCopyCommand}
                                        onCopied={onCommandCopied}
                                    />
                                </div>
                            )}
                        </div>
                    )
                ) : (
                    <div>
                        <h4 className="mb-1">Run from your project folder</h4>
                        <p className="text-sm text-muted">Open a terminal in the project root, then run:</p>
                        <WizardCommand
                            command={command}
                            showCopyButton
                            copied={commandCopied}
                            onCopy={onCopyCommand}
                            onCopied={onCommandCopied}
                        />
                        <div className="mt-3 text-xs text-muted">Requires Node.js 22.22 or later.</div>
                    </div>
                )}
            </div>
        </div>
    )
}
