import { useValues } from 'kea'
import { useState } from 'react'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSnack } from '@posthog/lemon-ui'

import api from 'lib/api'
import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

// Matches MAX_TASK_REPOSITORIES in products/cdp/backend/validation.py.
const MAX_REPOSITORIES = 10

function selectedRepositories(value: unknown): string[] {
    if (typeof value === 'string') {
        return value ? [value] : []
    }
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && !!item) : []
}

export default function CyclotronJobInputTaskRepository({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])
    const repositories = selectedRepositories(value)
    const selectedKeys = new Set(repositories.map((repository) => repository.toLowerCase()))

    // Which GitHub org to browse is view state only: each saved `owner/repo` already names its org.
    const [browsedIntegrationId, setBrowsedIntegrationId] = useState<number | null>(null)
    const integrationId = browsedIntegrationId ?? githubIntegrations[0]?.id

    if (integrationsLoading) {
        return (
            <LemonButton size="small" type="secondary" icon={<IconGithub />} disabled>
                GitHub
            </LemonButton>
        )
    }

    if (githubIntegrations.length === 0) {
        return (
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconGithub />}
                // Return to the current workflow editor after authorizing, not the workflows list,
                // so the user keeps their place instead of having to find and reopen the step.
                to={api.integrations.authorizeUrl({
                    kind: 'github',
                    next: window.location.pathname + window.location.search + window.location.hash,
                })}
                disableClientSideRouting
            >
                Connect GitHub
            </LemonButton>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {repositories.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    {repositories.map((repository) => (
                        <LemonSnack
                            key={repository}
                            title={`Remove ${repository}`}
                            onClose={() => onChange(repositories.filter((r) => r !== repository))}
                            data-attr="task-repository-picker-repository"
                        >
                            <span className="flex items-center gap-1 min-w-0">
                                <IconGithub className="shrink-0" />
                                <span className="truncate">{repository}</span>
                            </span>
                        </LemonSnack>
                    ))}
                </div>
            )}
            <div className="flex items-center gap-2 flex-wrap">
                {githubIntegrations.length > 1 && (
                    <LemonSelect
                        size="small"
                        value={integrationId}
                        options={githubIntegrations.map((integration) => ({
                            value: integration.id,
                            label: integration.display_name,
                        }))}
                        onChange={(id) => setBrowsedIntegrationId(id)}
                        data-attr="task-repository-picker-integration"
                    />
                )}
                <GitHubRepositoryCombobox
                    integrationId={integrationId}
                    value=""
                    placeholder={repositories.length ? 'Add another repository...' : 'Add a repository...'}
                    onChange={(repository) => {
                        if (repository && !selectedKeys.has(repository.toLowerCase())) {
                            onChange([...repositories, repository])
                        }
                    }}
                    repositoryFilter={(repository) => !selectedKeys.has(repository.full_name.toLowerCase())}
                    disabledReason={
                        repositories.length >= MAX_REPOSITORIES
                            ? `You can give a task up to ${MAX_REPOSITORIES} repositories`
                            : undefined
                    }
                />
            </div>
        </div>
    )
}
