import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowRight, IconCode } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSelect, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { repositorySelectorLogic } from './repositorySelectorLogic'

export interface RepositoryConfig {
    integrationId?: number
    organization?: string
    repository?: string
}

export interface RepositorySelectorProps {
    value: RepositoryConfig
    onChange: (config: RepositoryConfig) => void
}

export function RepositorySelector({ value, onChange }: RepositorySelectorProps): JSX.Element {
    const { githubRepositoriesLoading } = useValues(integrationsLogic)
    const { availableRepos, githubIntegrations, integrationsLoading } = useValues(repositorySelectorLogic)
    const { setOnChangeCallback, setCurrentConfig } = useActions(repositorySelectorLogic)

    // Set up the callback and current config when component mounts or value changes
    useEffect(() => {
        setOnChangeCallback(onChange)
        setCurrentConfig(value)
    }, [onChange, value, setOnChangeCallback, setCurrentConfig])

    const selectedRepoData = availableRepos.find((r) => r.integration_id === value.integrationId)

    if (integrationsLoading) {
        return (
            <div className="flex items-center gap-2 p-4 border rounded bg-bg-light">
                <Spinner /> Loading GitHub integrations...
            </div>
        )
    }

    if (githubIntegrations.length === 0) {
        return (
            <LemonCard className="p-6 text-center">
                <div className="space-y-4 flex flex-col items-center">
                    <IconCode className="mx-auto text-4xl text-muted" />
                    <div>
                        <h3 className="font-medium">Connect GitHub</h3>
                        <p className="text-muted text-sm">
                            Connect your GitHub account to create tasks from repositories.
                        </p>
                    </div>
                    <LemonButton
                        icon={<IconArrowRight />}
                        type="primary"
                        className="w-max"
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

    return (
        <div className="space-y-4">
            <div>
                <label className="block text-sm font-medium mb-2">GitHub Integration</label>
                <LemonSelect
                    value={value.integrationId}
                    onChange={(integrationId) => {
                        const integration = githubIntegrations.find((i: any) => i.id === integrationId)
                        const repoData = availableRepos.find((r: any) => r.integration_id === integrationId)

                        onChange({
                            ...value,
                            integrationId,
                            organization: repoData?.organization || integration?.config?.account?.name || 'GitHub',
                            repository: repoData?.repositories[0] || '',
                        })
                    }}
                    options={githubIntegrations.map((integration: any) => ({
                        value: integration.id,
                        label: `${integration.display_name} (${integration.config?.account?.name || 'GitHub'})`,
                    }))}
                    placeholder="Select GitHub integration..."
                />
            </div>

            {selectedRepoData && (
                <div>
                    <label className="block text-sm font-medium mb-2">Repository</label>
                    <LemonSelect
                        value={value.repository}
                        onChange={(repository) =>
                            onChange({
                                ...value,
                                repository,
                                organization: selectedRepoData.organization,
                            })
                        }
                        options={selectedRepoData.repositories.map((repo: string) => ({
                            value: repo,
                            label: `${selectedRepoData.organization}/${repo}`,
                        }))}
                        placeholder="Select repository..."
                    />
                </div>
            )}

            {githubRepositoriesLoading && availableRepos.length === 0 && (
                <div className="flex items-center gap-2 text-muted">
                    <Spinner /> Loading repositories...
                </div>
            )}
        </div>
    )
}
