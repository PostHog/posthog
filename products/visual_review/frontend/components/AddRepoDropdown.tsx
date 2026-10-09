import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { manageInstallationUrl } from 'lib/integrations/githubInstallationUrl'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { urls } from 'scenes/urls'

import type { IntegrationType } from '~/types'

import { visualReviewSettingsSceneLogic } from '../scenes/visualReviewSettingsSceneLogic'

export interface AddRepoDropdownProps {
    integration: IntegrationType
    /** Names the integration in the placeholder, so several pickers can be told apart. */
    showAccountName?: boolean
}

export function AddRepoDropdown({ integration, showAccountName }: AddRepoDropdownProps): JSX.Element {
    const { isRepoAddable, saving } = useValues(visualReviewSettingsSceneLogic)
    const { addRepo } = useActions(visualReviewSettingsSceneLogic)

    const installationId = integration.config?.installation_id
    const installationUrl = installationId
        ? manageInstallationUrl(installationId, integration.config?.account?.type, integration.config?.account?.name)
        : null

    return (
        <div className="flex items-center gap-1">
            <GitHubRepositoryPicker
                integrationId={integration.id}
                valueKey="full_name"
                repositoryFilter={isRepoAddable}
                onChange={(_, repository) => repository && addRepo(repository)}
                placeholder={showAccountName ? `Add from ${integration.display_name}...` : 'Add a repository...'}
                disabledReason={saving ? 'Adding repository...' : undefined}
                className="min-w-60"
            />
            <LemonButton
                type="tertiary"
                size="small"
                to={installationUrl ?? urls.settings('environment-integrations')}
                targetBlank={!!installationUrl}
                data-attr="visual-review-manage-github-access"
            >
                Manage access
            </LemonButton>
        </div>
    )
}
