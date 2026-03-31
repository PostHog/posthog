import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

export interface RepositoryConfig {
    integrationId?: number
    /** `owner/repo` (GitHub `full_name`), same as data warehouse / Cyclotron GitHub pickers */
    repository?: string
}

export interface RepositorySelectorProps {
    value: RepositoryConfig
    onChange: (config: RepositoryConfig) => void
}

export function RepositorySelector({ value, onChange }: RepositorySelectorProps): JSX.Element {
    const { integrationsLoading } = useValues(integrationsLogic)

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
                    <GitHubRepositoryPicker
                        integrationId={value.integrationId}
                        value={value.repository ?? ''}
                        onChange={(repo) => onChange({ ...value, repository: repo ?? undefined })}
                    />
                </div>
            ) : null}
        </div>
    )
}
