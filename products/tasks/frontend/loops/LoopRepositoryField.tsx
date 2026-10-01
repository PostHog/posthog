import { useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { Button, Skeleton, Text } from '@posthog/quill'

import api from 'lib/api'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { LoopRepositoryEntryApi } from '../generated/api.schemas'

export interface LoopRepositoryFieldProps {
    repository: LoopRepositoryEntryApi | null
    disabled?: boolean
    onChange: (repository: LoopRepositoryEntryApi | null) => void
}

export function LoopRepositoryField({ repository, disabled, onChange }: LoopRepositoryFieldProps): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const integrationId = repository?.github_integration_id ?? getIntegrationsByKind(['github'])[0]?.id

    if (integrationsLoading && !repository) {
        return <Skeleton className="h-8 w-48" />
    }
    if (!integrationId) {
        return (
            <div className="flex flex-col items-start gap-2">
                <Text size="xs" variant="muted">
                    Connect GitHub to let the loop work in a repository.
                </Text>
                <Button
                    variant="outline"
                    size="sm"
                    render={
                        <LinkPrimitive
                            to={api.integrations.authorizeUrl({ kind: 'github', next: window.location.pathname })}
                            disableClientSideRouting
                        />
                    }
                    data-attr="loop-connect-github"
                >
                    <IconGithub />
                    Connect GitHub
                </Button>
            </div>
        )
    }
    return (
        <div data-attr="loop-repository">
            <GitHubRepositoryCombobox
                integrationId={integrationId}
                value={repository?.full_name ?? ''}
                placeholder="No repository"
                showNoneOption
                disabled={disabled}
                onChange={(fullName) =>
                    onChange(fullName ? { github_integration_id: integrationId, full_name: fullName } : null)
                }
            />
        </div>
    )
}
