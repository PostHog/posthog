import { useValues } from 'kea'

import { IconGitBranch, IconGithub } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'
import { Button, ButtonGroup } from '@posthog/quill-primitives'

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
 * Compact repo/branch picker. With no GitHub integration it shows a single "Connect GitHub" chip;
 * with one or more it shows a joined [repo ▾][branch ▾] ButtonGroup (matching the posthog/code
 * composer), plus a leading integration switcher when several GitHub orgs are connected.
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
            <div className="flex items-center gap-2 flex-wrap">
                <Button variant="outline" size="sm" disabled>
                    <IconGithub className="shrink-0" />
                    GitHub
                </Button>
            </div>
        )
    }

    if (githubIntegrations.length === 0) {
        return (
            <div className="flex items-center gap-2 flex-wrap">
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
        <div className="flex items-center gap-2 flex-wrap">
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
                <ButtonGroup>
                    <GitHubRepositoryCombobox
                        integrationId={value.integrationId}
                        value={value.repository ?? ''}
                        onChange={handleRepositoryChange}
                        placeholder="No repo"
                        showNoneOption
                    />
                    {value.repository ? (
                        <GitHubBranchCombobox
                            integrationId={value.integrationId}
                            repo={value.repository}
                            value={value.branch ?? ''}
                            onChange={handleBranchChange}
                            placeholder="Default branch"
                            showNoneOption
                        />
                    ) : (
                        <Button variant="outline" size="sm" disabled aria-label="Branch">
                            <IconGitBranch className="shrink-0" />
                            Branch
                        </Button>
                    )}
                </ButtonGroup>
            ) : null}
        </div>
    )
}
