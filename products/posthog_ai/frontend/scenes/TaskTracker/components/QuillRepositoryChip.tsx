import { useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, ButtonGroup } from '@posthog/quill-primitives'

import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { cn } from 'lib/utils/css-classes'

import { COMPOSER_MENU_CLASS } from '../../../components/quill/composerMenuClass'
import type { RepositoryConfig } from '../../../types/taskTypes'
import { QuillGitHubAccountMenu } from './QuillGitHubAccountMenu'
import { QuillRepositorySummary } from './QuillRepositorySummary'

export interface QuillRepositoryChipProps {
    value: RepositoryConfig
    onChange: (config: RepositoryConfig) => void
    onRemove: () => void
    autoOpen: boolean
    isDefault: boolean
    onToggleDefault: () => void
}

export function QuillRepositoryChip({
    value,
    onChange,
    onRemove,
    autoOpen,
    isDefault,
    onToggleDefault,
}: QuillRepositoryChipProps): JSX.Element | null {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])
    const integrationId = value.integrationId

    if (integrationsLoading || githubIntegrations.length === 0 || !integrationId) {
        return null
    }

    const removeButton = (
        <Button
            variant="outline"
            size="icon-sm"
            aria-label="Remove repository"
            onClick={onRemove}
            data-attr="task-composer-remove-repository"
        >
            <IconX />
        </Button>
    )

    if (!value.repository) {
        return (
            <ButtonGroup>
                <QuillGitHubAccountMenu
                    integrationId={integrationId}
                    onSelect={(id) =>
                        onChange({ ...value, integrationId: id, repository: undefined, branch: undefined })
                    }
                />
                <GitHubRepositoryCombobox
                    integrationId={integrationId}
                    value=""
                    onChange={(repository) =>
                        onChange({ ...value, repository: repository ?? undefined, branch: undefined })
                    }
                    placeholder="Choose a repository"
                    contentSide="top"
                    contentClassName={cn('min-w-[280px]', COMPOSER_MENU_CLASS)}
                    defaultOpen={autoOpen}
                />
                {removeButton}
            </ButtonGroup>
        )
    }

    return (
        <ButtonGroup>
            <QuillRepositorySummary
                value={value}
                integrationId={integrationId}
                onChange={onChange}
                isDefault={isDefault}
                onToggleDefault={onToggleDefault}
            />
            {removeButton}
        </ButtonGroup>
    )
}
