import { useActions, useValues } from 'kea'

import { IconArrowRight, IconCopy, IconGear, IconGithub, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import type { RepoApi } from '../generated/api.schemas'
import { visualReviewSettingsLogic } from './visualReviewSettingsLogic'

function GitHubConnectPrompt(): JSX.Element {
    return (
        <div className="border rounded-lg p-6 text-center">
            <div className="space-y-4 flex flex-col items-center">
                <IconGithub className="text-4xl text-muted" />
                <div>
                    <h3 className="font-medium">Connect GitHub</h3>
                    <p className="text-muted text-sm">
                        Connect your GitHub account to enable baseline commits on approval.
                    </p>
                </div>
                <LemonButton
                    icon={<IconArrowRight />}
                    type="primary"
                    disableClientSideRouting
                    to={api.integrations.authorizeUrl({
                        kind: 'github',
                        next: window.location.pathname,
                    })}
                >
                    Connect GitHub
                </LemonButton>
            </div>
        </div>
    )
}

interface BaselinePathEditorProps {
    paths: Record<string, string>
    onChange: (paths: Record<string, string>) => void
}

function BaselinePathEditor({ paths, onChange }: BaselinePathEditorProps): JSX.Element {
    const entries = Object.entries(paths)

    const addEntry = (): void => {
        onChange({ ...paths, '': '' })
    }

    const updateKey = (oldKey: string, newKey: string): void => {
        const newPaths: Record<string, string> = {}
        for (const [k, v] of Object.entries(paths)) {
            newPaths[k === oldKey ? newKey : k] = v
        }
        onChange(newPaths)
    }

    const updateValue = (key: string, value: string): void => {
        onChange({ ...paths, [key]: value })
    }

    const removeEntry = (key: string): void => {
        const newPaths = { ...paths }
        delete newPaths[key]
        onChange(newPaths)
    }

    return (
        <div className="space-y-2">
            {entries.map(([key, value], index) => (
                <div key={index} className="flex gap-2 items-center">
                    <LemonInput
                        value={key}
                        onChange={(newKey) => updateKey(key, newKey)}
                        placeholder="Run type (e.g. storybook)"
                        className="flex-1"
                    />
                    <LemonInput
                        value={value}
                        onChange={(newValue) => updateValue(key, newValue)}
                        placeholder="Path (e.g. .snapshots.yml)"
                        className="flex-[2]"
                    />
                    <LemonButton icon={<IconTrash />} type="secondary" size="small" onClick={() => removeEntry(key)} />
                </div>
            ))}
            <LemonButton icon={<IconPlus />} type="secondary" size="small" onClick={addEntry}>
                Add path
            </LemonButton>
            {entries.length === 0 && (
                <div className="flex flex-wrap gap-2 mt-1">
                    <span className="text-muted text-xs">Quick add:</span>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => onChange({ ...paths, storybook: '.storybook/snapshots.yml' })}
                    >
                        Storybook
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => onChange({ ...paths, playwright: 'playwright/snapshots.yml' })}
                    >
                        Playwright
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

function generateSnapshotYml(repo: RepoApi, teamId: number): string {
    const apiUrl = window.location.origin
    return `version: 1
config:
    api: ${apiUrl}
    team: '${teamId}'
    repo: '${repo.id}'
snapshots: {}
`
}

function RepoCard({ repo }: { repo: RepoApi }): JSX.Element {
    const { editingRepoId } = useValues(visualReviewSettingsLogic)
    const { editRepo } = useActions(visualReviewSettingsLogic)
    const { currentTeamId } = useValues(teamLogic)

    const isEditing = editingRepoId === repo.id
    if (isEditing) {
        return <RepoEditForm />
    }

    const pathEntries = Object.entries(repo.baseline_file_paths || {})
    const snippet = currentTeamId ? generateSnapshotYml(repo, currentTeamId) : ''

    return (
        <div className="border rounded-lg p-4">
            <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                        <IconGithub className="text-muted shrink-0" />
                        <span className="font-medium truncate">{repo.repo_full_name}</span>
                    </div>
                    {pathEntries.length > 0 ? (
                        <div className="space-y-0.5">
                            {pathEntries.map(([runType, filePath]) => (
                                <div key={runType} className="text-xs text-muted font-mono">
                                    {runType} → {filePath}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <p className="text-xs text-muted-alt">No baseline paths configured</p>
                    )}
                    {repo.enable_pr_comments && <div className="text-xs text-muted mt-1">PR comments enabled</div>}
                </div>
                <LemonButton icon={<IconPencil />} type="secondary" size="small" onClick={() => editRepo(repo.id)}>
                    Edit
                </LemonButton>
            </div>

            {snippet && (
                <div className="mt-3 pt-3 border-t">
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-muted">Baseline config — paste into your snapshots.yml</span>
                        <LemonButton
                            icon={<IconCopy />}
                            size="xsmall"
                            type="secondary"
                            tooltip="Copy config snippet"
                            onClick={() => copyToClipboard(snippet, 'config snippet')}
                        />
                    </div>
                    <pre className="text-xs bg-bg-3000 rounded p-2 overflow-x-auto font-mono whitespace-pre">
                        {snippet.trim()}
                    </pre>
                </div>
            )}
        </div>
    )
}

function RepoEditForm(): JSX.Element {
    const { formValues, saving, hasChanges } = useValues(visualReviewSettingsLogic)
    const { setFormField, saveRepo, cancelEdit } = useActions(visualReviewSettingsLogic)

    return (
        <div className="border-2 border-primary rounded-lg p-4 space-y-4">
            <div>
                <label className="block text-sm font-medium mb-1">Baseline file paths</label>
                <p className="text-muted text-xs mb-1.5">Where baseline hashes are stored for each run type.</p>
                <BaselinePathEditor
                    paths={formValues.baseline_file_paths}
                    onChange={(paths) => setFormField('baseline_file_paths', paths)}
                />
            </div>

            <div>
                <LemonSwitch
                    checked={formValues.enable_pr_comments}
                    onChange={(checked) => setFormField('enable_pr_comments', checked)}
                    label="Post PR comments"
                    bordered
                />
                <p className="text-muted text-xs mt-1">
                    Post a comment on pull requests when visual changes are detected, prompting reviewers to approve.
                </p>
            </div>

            <div className="flex gap-2 pt-2">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={saveRepo}
                    loading={saving}
                    disabledReason={!hasChanges ? 'No changes' : undefined}
                >
                    Save
                </LemonButton>
                <LemonButton type="secondary" size="small" onClick={cancelEdit}>
                    Cancel
                </LemonButton>
            </div>
        </div>
    )
}

function AddRepoDropdown(): JSX.Element {
    const { availableRepos, existingRepoNames, saving, githubManageAccessUrl } = useValues(visualReviewSettingsLogic)
    const { addRepo } = useActions(visualReviewSettingsLogic)
    const { githubRepositoriesLoading } = useValues(integrationsLogic)

    const unaddedRepos = availableRepos.filter((r: GitHubRepoApi) => !existingRepoNames.has(r.full_name))

    if (githubRepositoriesLoading && availableRepos.length === 0) {
        return (
            <div className="flex items-center gap-2 text-muted text-sm">
                <Spinner /> Loading repositories...
            </div>
        )
    }

    const manageAccessUrl = githubManageAccessUrl ?? urls.settings('environment-integrations')

    return (
        <LemonSelect
            placeholder="Add a repository..."
            loading={saving}
            options={[
                {
                    options:
                        unaddedRepos.length > 0
                            ? unaddedRepos.map((repo: GitHubRepoApi) => ({
                                  value: repo.full_name,
                                  label: repo.full_name,
                              }))
                            : [
                                  {
                                      value: '__empty__' as any,
                                      label: 'No more repositories',
                                      disabledReason: 'All repositories have been added',
                                  },
                              ],
                    footer: (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            fullWidth
                            to={manageAccessUrl}
                            targetBlank={!!githubManageAccessUrl}
                            className="text-muted"
                        >
                            Manage access
                        </LemonButton>
                    ),
                },
            ]}
            onChange={(fullName) => {
                const repo = availableRepos.find((r: GitHubRepoApi) => r.full_name === fullName)
                if (repo) {
                    addRepo(repo)
                }
            }}
            value={null}
            size="small"
        />
    )
}

export function VisualReviewSettings(): JSX.Element {
    const { repos, reposLoading } = useValues(visualReviewSettingsLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const githubIntegrations = integrations?.filter((i: { kind: string }) => i.kind === 'github') || []
    const hasGitHub = githubIntegrations.length > 0

    if (reposLoading) {
        return (
            <div className="space-y-4 max-w-2xl">
                <LemonSkeleton className="h-24 w-full" />
                <LemonSkeleton className="h-24 w-full" />
            </div>
        )
    }

    return (
        <div className="space-y-4 max-w-2xl">
            {integrationsLoading ? (
                <div className="flex items-center gap-2 text-muted">
                    <Spinner /> Loading integrations...
                </div>
            ) : !hasGitHub ? (
                <GitHubConnectPrompt />
            ) : null}

            {hasGitHub && <AddRepoDropdown />}

            {repos.length === 0 && hasGitHub ? (
                <div className="border rounded-lg p-6 text-center text-muted">
                    <div className="space-y-2">
                        <IconGear className="text-2xl mx-auto" />
                        <p>No repos configured yet. Select a repository above to get started.</p>
                    </div>
                </div>
            ) : (
                repos.map((repo) => <RepoCard key={repo.id} repo={repo} />)
            )}
        </div>
    )
}
