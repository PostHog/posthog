import { useActions, useValues } from 'kea'

import { IconGitRepository, IconGithub, IconX } from '@posthog/icons'
import {
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import api from 'lib/api'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { spaceSceneLogic } from './spaceSceneLogic'
import { SpaceSettingsSection } from './SpaceSettingsSection'

const MAX_REPOSITORIES = 10

export function SpaceRepositories({ id }: { id: string }): JSX.Element | null {
    const { space, savingSpace } = useValues(spaceSceneLogic({ id }))
    const { updateSpace } = useActions(spaceSceneLogic({ id }))
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    if (!space) {
        return null
    }
    const integrationId = space.github_integration ?? getIntegrationsByKind(['github'])[0]?.id
    const repositories = space.repositories

    return (
        <SpaceSettingsSection
            label="Repositories"
            description="Sessions in this space start with these repositories checked out."
            action={
                integrationsLoading ? (
                    <Skeleton className="h-6 w-32" />
                ) : !integrationId ? null : repositories.length < MAX_REPOSITORIES ? (
                    <div data-attr="today-space-settings-add-repository">
                        <GitHubRepositoryCombobox
                            integrationId={integrationId}
                            value=""
                            placeholder="Add repository"
                            disabled={savingSpace}
                            onChange={(repository) => {
                                if (repository && !repositories.includes(repository)) {
                                    updateSpace({
                                        repositories: [...repositories, repository],
                                        github_integration: integrationId,
                                    })
                                }
                            }}
                        />
                    </div>
                ) : (
                    <Text size="xs" variant="muted">
                        {`Up to ${MAX_REPOSITORIES} repositories`}
                    </Text>
                )
            }
        >
            <ItemGroup combined>
                {repositories.map((repository) => (
                    <Item key={repository} variant="outline" size="sm" data-attr="today-space-settings-repository">
                        <ItemMedia variant="icon" className="text-muted-foreground">
                            <IconGitRepository />
                        </ItemMedia>
                        <ItemContent className="min-w-0">
                            <ItemTitle className="max-w-full">
                                <span className="min-w-0 truncate">{repository}</span>
                            </ItemTitle>
                        </ItemContent>
                        <ItemActions>
                            <Tooltip>
                                <TooltipTrigger
                                    delay={0}
                                    render={
                                        <Button
                                            size="icon-xs"
                                            aria-label={`Remove ${repository}`}
                                            disabled={savingSpace}
                                            onClick={() =>
                                                updateSpace({
                                                    repositories: repositories.filter((r) => r !== repository),
                                                })
                                            }
                                            data-attr="today-space-settings-remove-repository"
                                        />
                                    }
                                >
                                    <IconX />
                                </TooltipTrigger>
                                <TooltipContent>
                                    {savingSpace ? 'Saving your last change' : `Remove ${repository}`}
                                </TooltipContent>
                            </Tooltip>
                        </ItemActions>
                    </Item>
                ))}
                {!integrationsLoading && !integrationId ? (
                    <Item variant="outline" size="sm">
                        <ItemMedia variant="icon" className="text-muted-foreground">
                            <IconGithub />
                        </ItemMedia>
                        <ItemContent className="min-w-56">
                            <ItemTitle>GitHub isn’t connected</ItemTitle>
                            <ItemDescription>Connect GitHub to pick repositories for this space.</ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button
                                variant="outline"
                                size="sm"
                                render={
                                    <LinkPrimitive
                                        to={api.integrations.authorizeUrl({
                                            kind: 'github',
                                            next: window.location.pathname,
                                        })}
                                        disableClientSideRouting
                                    />
                                }
                                data-attr="today-space-settings-connect-github"
                            >
                                <IconGithub />
                                Connect GitHub
                            </Button>
                        </ItemActions>
                    </Item>
                ) : (
                    !repositories.length && (
                        <Item variant="outline" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    No repositories yet. Sessions start without code checked out.
                                </ItemDescription>
                            </ItemContent>
                        </Item>
                    )
                )}
            </ItemGroup>
        </SpaceSettingsSection>
    )
}
