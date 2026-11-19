import { useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, ButtonGroup } from '@posthog/quill-primitives'

import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { cn } from 'lib/utils/css-classes'

import { COMPOSER_MENU_CLASS } from '../../../components/quill/composerMenuClass'
import { gitlabProjectsLogic } from '../../../logics/gitlabProjectsLogic'
import type { RepositoryConfig } from '../../../types/taskTypes'
import type { GitlabProjectOption } from '../../../utils/gitlabProjects'
import { GitLabProjectCombobox } from './GitLabProjectCombobox'
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
    const { gitlabTaskIntegrations } = useValues(gitlabProjectsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])
    const integrationId = githubIntegrations.length > 0 ? value.integrationId : undefined
    const hasGitlab = gitlabTaskIntegrations.length > 0

    if (integrationsLoading || (!integrationId && !hasGitlab)) {
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

    // A GitLab task always starts from the project's default branch, so the selection carries no branch.
    const onGitlabProjectChange = ({ project, integrationId: gitlabIntegrationId }: GitlabProjectOption): void =>
        onChange({ ...value, repository: project, repositoryIntegrationId: gitlabIntegrationId, branch: undefined })
    const gitlabPicker = (selected: string): JSX.Element => (
        <GitLabProjectCombobox
            value={selected}
            onChange={onGitlabProjectChange}
            contentSide="top"
            contentClassName={cn('min-w-[280px]', COMPOSER_MENU_CLASS)}
        />
    )

    if (hasGitlab && value.repositoryIntegrationId && value.repository) {
        return (
            <ButtonGroup>
                {gitlabPicker(value.repository)}
                {removeButton}
            </ButtonGroup>
        )
    }

    if (!value.repository || !integrationId) {
        return (
            <ButtonGroup>
                {integrationId ? (
                    <>
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
                                onChange({
                                    ...value,
                                    repository: repository ?? undefined,
                                    branch: undefined,
                                    repositoryIntegrationId: undefined,
                                })
                            }
                            placeholder="Choose a repository"
                            contentSide="top"
                            contentClassName={cn('min-w-[280px]', COMPOSER_MENU_CLASS)}
                            defaultOpen={autoOpen}
                        />
                    </>
                ) : null}
                {hasGitlab && gitlabPicker('')}
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
