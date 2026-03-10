import { useActions, useValues } from 'kea'

import { IconArrowRight, IconGear, IconGithub, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { GitHubRepoApi } from '~/generated/core/api.schemas'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { RepoApi } from '../generated/api.schemas'
import { visualReviewSettingsSceneLogic } from './visualReviewSettingsSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewSettingsScene,
    logic: visualReviewSettingsSceneLogic,
}

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

function RepoCard({ repo }: { repo: RepoApi }): JSX.Element {
    const { editingRepoId } = useValues(visualReviewSettingsSceneLogic)
    const { editRepo } = useActions(visualReviewSettingsSceneLogic)

    const isEditing = editingRepoId === repo.id
    if (isEditing) {
        return <RepoEditForm />
    }

    const pathEntries = Object.entries(repo.baseline_file_paths || {})

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
                </div>
                <LemonButton icon={<IconPencil />} type="secondary" size="small" onClick={() => editRepo(repo.id)}>
                    Edit
                </LemonButton>
            </div>
        </div>
    )
}

function RepoEditForm(): JSX.Element {
    const { formValues, saving, hasChanges } = useValues(visualReviewSettingsSceneLogic)
    const { setFormField, saveRepo, cancelEdit } = useActions(visualReviewSettingsSceneLogic)

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
    const { availableRepos, existingRepoNames, saving, githubManageAccessUrl } =
        useValues(visualReviewSettingsSceneLogic)
    const { addRepo } = useActions(visualReviewSettingsSceneLogic)
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

export function VisualReviewSettingsScene(): JSX.Element {
    const { repos, reposLoading } = useValues(visualReviewSettingsSceneLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const githubIntegrations = integrations?.filter((i: { kind: string }) => i.kind === 'github') || []
    const hasGitHub = githubIntegrations.length > 0

    if (reposLoading) {
        return (
            <SceneContent>
                <SceneTitleSection name="Visual review settings" resourceType={{ type: 'visual_review' }} />
                <div className="space-y-4 max-w-2xl">
                    <LemonSkeleton className="h-24 w-full" />
                    <LemonSkeleton className="h-24 w-full" />
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Visual review settings"
                resourceType={{ type: 'visual_review' }}
                actions={hasGitHub ? <AddRepoDropdown /> : undefined}
            />

            <div className="space-y-4 max-w-2xl">
                {integrationsLoading ? (
                    <div className="flex items-center gap-2 text-muted">
                        <Spinner /> Loading integrations...
                    </div>
                ) : !hasGitHub ? (
                    <GitHubConnectPrompt />
                ) : null}

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
        </SceneContent>
    )
}

export default VisualReviewSettingsScene
