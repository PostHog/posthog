import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { Button, Chip, ChipClose, Skeleton, Text } from '@posthog/quill'

import api from 'lib/api'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { spaceSceneLogic } from './spaceSceneLogic'

const MAX_REPOSITORIES = 10

export function SpaceRepositories({ id }: { id: string }): JSX.Element | null {
    const { space, savingSpace } = useValues(spaceSceneLogic({ id }))
    const { updateSpace } = useActions(spaceSceneLogic({ id }))
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    if (!space) {
        return null
    }
    const githubIntegrations = getIntegrationsByKind(['github'])
    const integrationId = space.github_integration ?? githubIntegrations[0]?.id
    const repositories = space.repositories

    return (
        <div className="flex flex-col items-start gap-2">
            {repositories.length ? (
                <div className="flex flex-wrap gap-1">
                    {repositories.map((repository) => (
                        <Chip key={repository} data-attr="today-space-settings-repository">
                            {repository}
                            <ChipClose
                                aria-label={`Remove ${repository}`}
                                disabled={savingSpace}
                                onClick={() =>
                                    updateSpace({ repositories: repositories.filter((r) => r !== repository) })
                                }
                            />
                        </Chip>
                    ))}
                </div>
            ) : (
                <Text size="sm" variant="muted">
                    No repositories yet.
                </Text>
            )}
            {integrationsLoading ? (
                <Skeleton className="h-8 w-60" />
            ) : !integrationId ? (
                <Button
                    variant="outline"
                    render={
                        <LinkPrimitive
                            to={api.integrations.authorizeUrl({ kind: 'github', next: window.location.pathname })}
                            disableClientSideRouting
                        />
                    }
                    data-attr="today-space-settings-connect-github"
                >
                    <IconGithub />
                    Connect GitHub
                </Button>
            ) : repositories.length < MAX_REPOSITORIES ? (
                <div className="w-full max-w-100">
                    <GitHubRepositoryCombobox
                        integrationId={integrationId}
                        value=""
                        placeholder="Add a repository"
                        disabledReason={savingSpace ? 'Saving your last change' : undefined}
                        onChange={(repository) => {
                            if (repository && !repositories.includes(repository)) {
                                updateSpace({
                                    repositories: [...repositories, repository],
                                    github_integration: integrationId,
                                })
                            }
                        }}
                        fullWidth
                    />
                </div>
            ) : (
                <Text size="sm" variant="muted">
                    A space can have up to {MAX_REPOSITORIES} repositories.
                </Text>
            )}
        </div>
    )
}
