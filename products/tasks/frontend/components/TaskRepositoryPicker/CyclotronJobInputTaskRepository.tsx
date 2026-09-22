import { useValues } from 'kea'
import { useState } from 'react'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import api from 'lib/api'
import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

export default function CyclotronJobInputTaskRepository({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])

    // Which GitHub org to browse is view state only: the saved value is the `owner/repo` string,
    // which already names the org, so the choice never needs to persist.
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
                value={typeof value === 'string' ? value : ''}
                onChange={(repository) => onChange(repository ?? null)}
                showNoneOption
            />
        </div>
    )
}
