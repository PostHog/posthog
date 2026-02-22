import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowRight, IconGithub, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonSelect, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { visualReviewSettingsSceneLogic } from './visualReviewSettingsSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewSettingsScene,
    logic: visualReviewSettingsSceneLogic,
}

function GitHubConnectPrompt(): JSX.Element {
    return (
        <LemonCard className="p-6 text-center">
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
        </LemonCard>
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
                        placeholder="Run type (e.g., storybook)"
                        className="flex-1"
                    />
                    <LemonInput
                        value={value}
                        onChange={(newValue) => updateValue(key, newValue)}
                        placeholder="Path (e.g., .snapshots.yml)"
                        className="flex-[2]"
                    />
                    <LemonButton icon={<IconTrash />} type="secondary" size="small" onClick={() => removeEntry(key)} />
                </div>
            ))}
            <LemonButton icon={<IconPlus />} type="secondary" size="small" onClick={addEntry}>
                Add baseline path
            </LemonButton>
        </div>
    )
}

export function VisualReviewSettingsScene(): JSX.Element {
    const { repo, repoLoading, availableRepos, saving } = useValues(visualReviewSettingsSceneLogic)
    const { loadRepo, saveRepo } = useActions(visualReviewSettingsSceneLogic)
    const { integrations, integrationsLoading, githubRepositoriesLoading } = useValues(integrationsLogic)
    const { loadGitHubRepositories } = useActions(integrationsLogic)

    const [repoFullName, setRepoFullName] = useState('')
    const [baselineFilePaths, setBaselineFilePaths] = useState<Record<string, string>>({})

    const githubIntegrations = integrations?.filter((i: { kind: string }) => i.kind === 'github') || []

    // Load repo on mount (integrations are loaded by integrationsLogic's afterMount)
    useEffect(() => {
        loadRepo()
    }, [loadRepo])

    // Load repos when integrations are loaded
    useEffect(() => {
        githubIntegrations.forEach((integration: { id: number }) => {
            loadGitHubRepositories(integration.id)
        })
    }, [integrations?.length, githubIntegrations, loadGitHubRepositories])

    // Sync form state when repo loads
    useEffect(() => {
        if (repo) {
            setRepoFullName(repo.repo_full_name || '')
            setBaselineFilePaths(repo.baseline_file_paths || {})
        }
    }, [repo])

    const handleSave = (): void => {
        saveRepo({
            repo_full_name: repoFullName,
            baseline_file_paths: baselineFilePaths,
        })
    }

    const hasChanges = repo
        ? repoFullName !== (repo.repo_full_name || '') ||
          JSON.stringify(baselineFilePaths) !== JSON.stringify(repo.baseline_file_paths || {})
        : repoFullName !== '' || Object.keys(baselineFilePaths).length > 0

    if (repoLoading) {
        return (
            <SceneContent>
                <SceneTitleSection name="Visual review settings" resourceType={{ type: 'visual_review' }} />
                <div className="space-y-4">
                    <LemonSkeleton className="h-10 w-full" />
                    <LemonSkeleton className="h-10 w-full" />
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
                        type="primary"
                        onClick={handleSave}
                        loading={saving}
                        disabledReason={!hasChanges ? 'No changes to save' : undefined}
                    >
                        Save settings
                    </LemonButton>
                }
            />

            <div className="space-y-6 max-w-2xl">
                <p className="text-muted text-sm">
                    Configure where approved baselines are committed. One configuration covers all your run types
                    (Storybook, Playwright, etc.) — just add a baseline path for each.
                </p>

                {/* GitHub Integration Check */}
                {integrationsLoading ? (
                    <div className="flex items-center gap-2">
                        <Spinner /> Loading integrations...
                    </div>
                ) : githubIntegrations.length === 0 ? (
                    <GitHubConnectPrompt />
                ) : (
                    <>
                        {/* Repository Selection */}
                        <div>
                            <label className="block text-sm font-medium mb-2">GitHub Repository</label>
                            <p className="text-muted text-sm mb-2">
                                Select the repository where baselines will be committed on approval.
                            </p>
                            {githubRepositoriesLoading && availableRepos.length === 0 ? (
                                <div className="flex items-center gap-2 text-muted">
                                    <Spinner /> Loading repositories...
                                </div>
                            ) : (
                                <LemonSelect
                                    value={repoFullName}
                                    onChange={(value) => setRepoFullName(value || '')}
                                    options={availableRepos.map((repo: string) => ({
                                        value: repo,
                                        label: repo,
                                    }))}
                                    placeholder="Select a repository..."
                                    className="w-full"
                                />
                            )}
                        </div>

                        {/* Baseline File Paths */}
                        <div>
                            <label className="block text-sm font-medium mb-2">Baseline file paths</label>
                            <p className="text-muted text-sm mb-2">
                                Configure where baseline hashes are stored for each run type. The CLI reads these files
                                to determine expected snapshots.
                            </p>
                            <BaselinePathEditor paths={baselineFilePaths} onChange={setBaselineFilePaths} />
                            {Object.keys(baselineFilePaths).length === 0 && (
                                <div className="mt-3 flex flex-wrap gap-2">
                                    <span className="text-muted text-xs">Quick add:</span>
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        onClick={() =>
                                            setBaselineFilePaths({
                                                ...baselineFilePaths,
                                                storybook: '.storybook/snapshots.yml',
                                            })
                                        }
                                    >
                                        Storybook
                                    </LemonButton>
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        onClick={() =>
                                            setBaselineFilePaths({
                                                ...baselineFilePaths,
                                                playwright: 'playwright/snapshots.yml',
                                            })
                                        }
                                    >
                                        Playwright
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    </>
                )}
            </div>
        </SceneContent>
    )
}

export default VisualReviewSettingsScene
