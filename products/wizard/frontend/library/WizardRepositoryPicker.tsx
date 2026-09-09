import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

export function isWizardRepositoryEligible(repository: GitHubRepoApi): boolean {
    return !repository.archived
}

export function WizardRepositoryPicker({
    integrationId,
    value,
    onChange,
    disabledReason,
}: {
    integrationId: number
    value: string
    onChange: (repository: string) => void
    disabledReason?: string
}): JSX.Element {
    return (
        <GitHubRepositoryCombobox
            integrationId={integrationId}
            value={value}
            onChange={(repository) => onChange(repository ?? '')}
            disabled={!!disabledReason}
            repositoryFilter={isWizardRepositoryEligible}
            placeholder="Select a repository"
            fullWidth
        />
    )
}
