import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

import type { RepositoryConfig } from '../../../types/taskTypes'

export interface RepositorySelectorProps {
    value: RepositoryConfig
    onChange: (config: RepositoryConfig) => void
}

export function RepositorySelector({ value, onChange }: RepositorySelectorProps): JSX.Element {
    const { integrationsLoading } = useValues(integrationsLogic)

    // The picker selects on `owner/repo`, which is exactly the format the Task API expects.
    const handleRepositoryChange = (repository: string | null): void => {
        onChange({ ...value, repository: repository ?? undefined })
    }

    if (integrationsLoading) {
        return <LemonSkeleton className="h-24" />
    }

    return (
        <div className="space-y-4">
            <div>
                <label className="block text-sm font-medium mb-2">GitHub integration</label>
                <IntegrationChoice
                    integration="github"
                    value={value.integrationId}
                    onChange={(integrationId) =>
                        onChange({
                            ...value,
                            integrationId: integrationId ?? undefined,
                            repository: undefined,
                        })
                    }
                    redirectUrl={urls.taskTracker()}
                />
            </div>

            {value.integrationId ? (
                <div>
                    <label className="block text-sm font-medium mb-2">Repository</label>
                    <GitHubRepositoryCombobox
                        integrationId={value.integrationId}
                        value={value.repository ?? ''}
                        onChange={handleRepositoryChange}
                    />
                </div>
            ) : null}
        </div>
    )
}
