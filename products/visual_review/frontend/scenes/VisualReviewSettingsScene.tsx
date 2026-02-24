import { useActions, useValues } from 'kea'

import { IconArrowRight, IconGear, IconGithub, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SceneExport } from 'scenes/sceneTypes'

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
                        <IconGear className="text-muted shrink-0" />
                        <span className="font-medium truncate">{repo.name}</span>
                    </div>
                    {repo.repo_full_name ? (
                        <div className="flex items-center gap-1.5 text-sm text-muted mb-2">
                            <IconGithub className="shrink-0" />
                            <span className="truncate">{repo.repo_full_name}</span>
                        </div>
                    ) : (
                        <p className="text-sm text-muted-alt mb-2">No GitHub repository configured</p>
                    )}
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
    const { formValues, saving, hasChanges, editingRepoId, availableRepos } = useValues(visualReviewSettingsSceneLogic)
    const { setFormField, saveRepo, cancelEdit } = useActions(visualReviewSettingsSceneLogic)
    const { githubRepositoriesLoading } = useValues(integrationsLogic)

    const isNew = editingRepoId === 'new'

    return (
        <div className="border-2 border-primary rounded-lg p-4 space-y-4">
            <div>
                <label className="block text-sm font-medium mb-1">Name</label>
                <LemonInput
                    value={formValues.name}
                    onChange={(value) => setFormField('name', value)}
                    placeholder="e.g. posthog/posthog"
                />
            </div>

            <div>
                <label className="block text-sm font-medium mb-1">GitHub repository</label>
                <p className="text-muted text-xs mb-1.5">Where baselines are committed on approval.</p>
                {githubRepositoriesLoading && availableRepos.length === 0 ? (
                    <div className="flex items-center gap-2 text-muted text-sm">
                        <Spinner /> Loading repositories...
                    </div>
                ) : (
                    <LemonSelect
                        value={formValues.repo_full_name}
                        onChange={(value) => setFormField('repo_full_name', value || '')}
                        options={availableRepos.map((repo: string) => ({
                            value: repo,
                            label: repo,
                        }))}
                        placeholder="Select a repository..."
                        className="w-full"
                    />
                )}
            </div>

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
                    disabledReason={
                        isNew && !formValues.name.trim() ? 'Name is required' : !hasChanges ? 'No changes' : undefined
                    }
                >
                    {isNew ? 'Create' : 'Save'}
                </LemonButton>
                <LemonButton type="secondary" size="small" onClick={cancelEdit}>
                    Cancel
                </LemonButton>
            </div>
        </div>
    )
}

export function VisualReviewSettingsScene(): JSX.Element {
    const { repos, reposLoading, editingRepoId } = useValues(visualReviewSettingsSceneLogic)
    const { newRepo } = useActions(visualReviewSettingsSceneLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const githubIntegrations = integrations?.filter((i: { kind: string }) => i.kind === 'github') || []

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
                actions={
                    <LemonButton
                        icon={<IconPlus />}
                        type="secondary"
                        onClick={newRepo}
                        disabledReason={editingRepoId ? 'Finish editing first' : undefined}
                    >
                        Add repo
                    </LemonButton>
                }
            />

            <div className="space-y-4 max-w-2xl">
                {/* GitHub integration check */}
                {integrationsLoading ? (
                    <div className="flex items-center gap-2 text-muted">
                        <Spinner /> Loading integrations...
                    </div>
                ) : githubIntegrations.length === 0 ? (
                    <GitHubConnectPrompt />
                ) : null}

                {/* New repo form */}
                {editingRepoId === 'new' && <RepoEditForm />}

                {/* Existing repos */}
                {repos.length === 0 && !editingRepoId ? (
                    <div className="border rounded-lg p-6 text-center text-muted">
                        <p>No repos configured yet. Add one to get started.</p>
                    </div>
                ) : (
                    repos.map((repo) => <RepoCard key={repo.id} repo={repo} />)
                )}
            </div>
        </SceneContent>
    )
}

export default VisualReviewSettingsScene
