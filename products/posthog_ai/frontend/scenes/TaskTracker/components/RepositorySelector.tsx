import { useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import api from 'lib/api'
import { GitHubBranchCombobox } from 'lib/integrations/GitHubBranchCombobox'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

import type { RepositoryConfig } from '../../../types/taskTypes'

export interface RepositorySelectorProps {
    value: RepositoryConfig
    onChange: (config: RepositoryConfig) => void
}

const githubAuthorizeUrl = api.integrations.authorizeUrl({ kind: 'github', next: urls.taskTracker() })

/**
 * Compact repo/branch picker rendered as chips inside the composer footer. With no GitHub integration it
 * shows a single "Connect GitHub" chip; with one or more it shows [repo ▾] then (once a repo is picked)
 * [branch ▾], plus a leading integration switcher when several GitHub orgs are connected.
 */
export function RepositorySelector({ value, onChange }: RepositorySelectorProps): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])

    // Selecting a repo clears the branch so GitHubBranchCombobox auto-picks the new repo's default branch.
    const handleRepositoryChange = (repository: string | null): void => {
        onChange({ ...value, repository: repository ?? undefined, branch: undefined })
    }

    const handleBranchChange = (branch: string | null): void => {
        onChange({ ...value, branch: branch ?? undefined })
    }

    const handleIntegrationChange = (integrationId: number): void => {
        onChange({ ...value, integrationId, repository: undefined, branch: undefined })
    }

    if (integrationsLoading) {
        // Inert placeholder so we never flash "Connect GitHub" before the integration list resolves.
        return (
            <div className="flex items-center gap-1 flex-wrap pl-2">
                <LemonButton size="small" type="secondary" icon={<IconGithub />} disabledReason="Loading…">
                    GitHub
                </LemonButton>
            </div>
        )
    }

    if (githubIntegrations.length === 0) {
        return (
            <div className="flex items-center gap-1 flex-wrap pl-2">
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconGithub />}
                    to={githubAuthorizeUrl}
                    disableClientSideRouting
                >
                    Connect GitHub
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex items-center gap-1 flex-wrap pl-2">
            {githubIntegrations.length > 1 && (
                <LemonMenu
                    items={[
                        {
                            items: githubIntegrations.map((integration) => ({
                                icon: (
                                    <img
                                        src={integration.icon_url}
                                        alt={`${integration.display_name} icon`}
                                        className="w-5 h-5 rounded"
                                    />
                                ),
                                label: integration.display_name,
                                active: integration.id === value.integrationId,
                                onClick: () => handleIntegrationChange(integration.id),
                            })),
                        },
                        {
                            items: [
                                { to: githubAuthorizeUrl, disableClientSideRouting: true, label: 'Connect another' },
                                { to: urls.settings('project-integrations'), label: 'Manage integrations' },
                            ],
                        },
                    ]}
                >
                    <LemonButton size="small" type="secondary" icon={<IconGithub />}>
                        {githubIntegrations.find((i) => i.id === value.integrationId)?.display_name ?? 'GitHub'}
                    </LemonButton>
                </LemonMenu>
            )}

            {value.integrationId ? (
                <GitHubRepositoryCombobox
                    integrationId={value.integrationId}
                    value={value.repository ?? ''}
                    onChange={handleRepositoryChange}
                />
            ) : null}

            {value.integrationId && value.repository ? (
                <GitHubBranchCombobox
                    integrationId={value.integrationId}
                    repo={value.repository}
                    value={value.branch ?? ''}
                    onChange={handleBranchChange}
                />
            ) : null}
        </div>
    )
}
