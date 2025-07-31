import { useEffect } from 'react'
import { LemonButton, LemonCard, LemonTag, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconGithub, IconOpenInNew, IconBranch, IconRefresh } from 'lib/lemon-ui/icons'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

export interface GitHubIntegrationSettingsProps {
    teamId: number
}

export function GitHubIntegrationSettings({ }: GitHubIntegrationSettingsProps): JSX.Element {
    const { integrations, integrationsLoading, githubRepositoriesLoading, getGitHubRepositories } = useValues(integrationsLogic)
    const { loadIntegrations, loadGitHubRepositories } = useActions(integrationsLogic)

    const githubIntegration = integrations?.find((integration: any) => integration.kind === 'github')
    const repositories = githubIntegration ? getGitHubRepositories(githubIntegration.id) : []

    useEffect(() => {
        loadIntegrations()
    }, [loadIntegrations])

    useEffect(() => {
        if (githubIntegration) {
            loadGitHubRepositories(githubIntegration.id)
        }
    }, [githubIntegration, loadGitHubRepositories])

    const handleManageIntegration = () => {
        router.actions.push(urls.settings('environment-integrations'))
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <IconGithub className="text-2xl" />
                <h2 className="text-xl font-semibold">GitHub Integration</h2>
                {githubIntegration && <LemonTag type="success">Connected</LemonTag>}
            </div>

            <LemonCard className="p-6">
                {githubIntegration ? (
                    <div className="space-y-4">
                        <div>
                            <h3 className="font-medium">Connected to {githubIntegration.display_name}</h3>
                            <p className="text-muted text-sm">
                                Issues moved to "To Do" will automatically create branches and pull requests.
                            </p>
                        </div>
                        
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <h4 className="font-medium flex items-center gap-2">
                                    <IconBranch className="text-lg" />
                                    Accessible Repositories
                                </h4>
                                <div className="flex gap-1">
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        icon={<IconRefresh />}
                                        onClick={() => githubIntegration && loadGitHubRepositories(githubIntegration.id)}
                                        loading={githubRepositoriesLoading}
                                        tooltip="Refresh repositories"
                                    />
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        icon={<IconOpenInNew />}
                                        onClick={() => {
                                            const installationId = githubIntegration?.config?.installation_id
                                            if (installationId) {
                                                window.open(`https://github.com/settings/installations/${installationId}`, '_blank')
                                            }
                                        }}
                                        tooltip="Manage repository access on GitHub"
                                    />
                                </div>
                            </div>
                            {githubRepositoriesLoading ? (
                                <div className="flex items-center gap-2 text-muted text-sm">
                                    <Spinner className="text-lg" />
                                    Loading repositories...
                                </div>
                            ) : repositories.length > 0 ? (
                                <div className="space-y-1">
                                    {repositories.map((repo, index) => (
                                        <div key={index} className="flex items-center gap-2 text-sm bg-accent-3000 rounded px-2 py-1">
                                            <IconBranch className="text-muted" />
                                            <span className="font-mono">{githubIntegration.config?.account?.name || 'GitHub'}/{repo}</span>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <div className="text-muted text-sm">
                                    <p>No repositories found.</p>
                                    <p className="mt-1">
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            icon={<IconOpenInNew />}
                                            onClick={() => {
                                                const installationId = githubIntegration?.config?.installation_id
                                                if (installationId) {
                                                    window.open(`https://github.com/settings/installations/${installationId}`, '_blank')
                                                }
                                            }}
                                        >
                                            Configure repository access
                                        </LemonButton>
                                    </p>
                                </div>
                            )}
                        </div>
                        
                        <LemonButton
                            type="secondary"
                            icon={<IconOpenInNew />}
                            onClick={handleManageIntegration}
                        >
                            Manage Integration
                        </LemonButton>
                    </div>
                ) : (
                    <div className="space-y-4">
                        <div>
                            <h3 className="font-medium">No GitHub integration</h3>
                            <p className="text-muted text-sm">
                                Connect GitHub to enable automatic branch creation and pull requests for issues.
                            </p>
                        </div>
                        <LemonButton
                            type="primary"
                            onClick={handleManageIntegration}
                            loading={integrationsLoading}
                        >
                            Connect GitHub
                        </LemonButton>
                    </div>
                )}
            </LemonCard>
        </div>
    )
}