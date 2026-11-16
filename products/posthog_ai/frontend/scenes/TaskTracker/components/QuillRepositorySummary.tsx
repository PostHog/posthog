import { useValues } from 'kea'
import { useId } from 'react'

import { IconGithub } from '@posthog/icons'
import { Button, Label, Popover, PopoverContent, PopoverTrigger, Switch } from '@posthog/quill-primitives'

import { GitHubBranchCombobox } from 'lib/integrations/GitHubBranchCombobox'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { useGitHubDefaultBranch } from 'lib/integrations/useGitHubDefaultBranch'
import { cn } from 'lib/utils/css-classes'

import { COMPOSER_MENU_CLASS } from '../../../components/quill/composerMenuClass'
import type { RepositoryConfig } from '../../../types/taskTypes'
import { QuillGitHubAccountMenu } from './QuillGitHubAccountMenu'

const PANEL_FIELD_CLASS = 'h-7 w-full justify-start'
const PANEL_LIST_CLASS = cn('w-(--anchor-width) min-w-(--anchor-width)', COMPOSER_MENU_CLASS)

export interface QuillRepositorySummaryProps {
    value: RepositoryConfig
    integrationId: number
    onChange: (config: RepositoryConfig) => void
    isDefault: boolean
    onToggleDefault: () => void
}

export function QuillRepositorySummary({
    value,
    integrationId,
    onChange,
    isDefault,
    onToggleDefault,
}: QuillRepositorySummaryProps): JSX.Element {
    const repository = value.repository ?? ''
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])
    const defaultSwitchId = useId()
    const onBranchChange = (branch: string | null): void => onChange({ ...value, branch: branch ?? undefined })
    useGitHubDefaultBranch({ integrationId, repo: repository, value: value.branch ?? '', onChange: onBranchChange })

    return (
        <Popover>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        size="sm"
                        title={value.branch ? `${repository} on ${value.branch}` : repository}
                        data-attr="task-composer-repository-chip"
                    >
                        <IconGithub className="shrink-0" />
                        <span className="max-w-40 truncate">{repository.split('/').pop()}</span>
                        {value.branch && (
                            <span className="max-w-28 truncate text-muted-foreground">{value.branch}</span>
                        )}
                    </Button>
                }
            />
            <PopoverContent side="top" align="start" sideOffset={6} className={cn('w-72 gap-3', COMPOSER_MENU_CLASS)}>
                {githubIntegrations.length > 1 && (
                    <div className="flex flex-col gap-1">
                        <Label>GitHub account</Label>
                        <QuillGitHubAccountMenu
                            integrationId={integrationId}
                            onSelect={(id) =>
                                onChange({ ...value, integrationId: id, repository: undefined, branch: undefined })
                            }
                            fullWidth
                        />
                    </div>
                )}
                <div className="flex flex-col gap-1">
                    <Label>Repository</Label>
                    <GitHubRepositoryCombobox
                        integrationId={integrationId}
                        value={repository}
                        onChange={(next) => onChange({ ...value, repository: next ?? undefined, branch: undefined })}
                        triggerClassName={PANEL_FIELD_CLASS}
                        contentSide="top"
                        contentClassName={PANEL_LIST_CLASS}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <Label>Branch</Label>
                    <GitHubBranchCombobox
                        integrationId={integrationId}
                        repo={repository}
                        value={value.branch ?? ''}
                        onChange={onBranchChange}
                        triggerClassName={PANEL_FIELD_CLASS}
                        contentSide="top"
                        contentClassName={PANEL_LIST_CLASS}
                    />
                </div>
                <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
                    <Label htmlFor={defaultSwitchId}>Start new chats with this repository</Label>
                    <Switch
                        id={defaultSwitchId}
                        checked={isDefault}
                        onCheckedChange={onToggleDefault}
                        data-attr="task-composer-default-repository"
                    />
                </div>
            </PopoverContent>
        </Popover>
    )
}
