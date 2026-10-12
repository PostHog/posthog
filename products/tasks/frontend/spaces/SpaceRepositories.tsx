import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconGitRepository, IconGithub, IconX } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    Chip,
    ChipClose,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Spinner,
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
    const [pendingRepositories, setPendingRepositories] = useState<string[] | null>(null)
    const [saveFailed, setSaveFailed] = useState(false)

    useEffect(() => {
        if (savingSpace || pendingRepositories === null) {
            return
        }
        setSaveFailed((space?.repositories ?? []).join('\n') !== pendingRepositories.join('\n'))
        setPendingRepositories(null)
    }, [savingSpace, pendingRepositories, space?.repositories])

    if (!space) {
        return null
    }
    const integrationId = space.github_integration ?? getIntegrationsByKind(['github'])[0]?.id
    const repositories = space.repositories
    const saving = savingSpace && pendingRepositories !== null

    const saveRepositories = (next: string[]): void => {
        setSaveFailed(false)
        setPendingRepositories(next)
        updateSpace({ repositories: next, github_integration: next.length && integrationId ? integrationId : null })
    }

    return (
        <SpaceSettingsSection
            label="Repositories"
            description="Sessions in this space start with these repositories checked out."
        >
            <Card size="sm">
                <CardContent className="flex flex-col gap-2">
                    {integrationsLoading ? (
                        <Skeleton className="h-7 w-40" />
                    ) : !integrationId ? (
                        <Item size="sm" className="p-0">
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
                        <div className="flex min-h-7 max-w-full flex-wrap items-center gap-2">
                            {repositories.map((repository) => (
                                <Chip
                                    key={repository}
                                    className="max-w-full"
                                    data-attr="today-space-settings-repository"
                                >
                                    <IconGitRepository className="shrink-0 text-muted-foreground" />
                                    <span className="min-w-0 truncate">{repository}</span>
                                    <Tooltip>
                                        <TooltipTrigger
                                            delay={0}
                                            render={
                                                <ChipClose
                                                    aria-label={`Remove ${repository}`}
                                                    disabled={savingSpace}
                                                    onClick={() =>
                                                        saveRepositories(repositories.filter((r) => r !== repository))
                                                    }
                                                    data-attr="today-space-settings-remove-repository"
                                                />
                                            }
                                        >
                                            <IconX />
                                        </TooltipTrigger>
                                        <TooltipContent>{`Remove ${repository}`}</TooltipContent>
                                    </Tooltip>
                                </Chip>
                            ))}
                            {repositories.length < MAX_REPOSITORIES ? (
                                <div data-attr="today-space-settings-add-repository">
                                    <GitHubRepositoryCombobox
                                        integrationId={integrationId}
                                        value=""
                                        placeholder={repositories.length ? 'Add…' : 'Add repository…'}
                                        disabled={savingSpace}
                                        onChange={(repository) => {
                                            if (repository && !repositories.includes(repository)) {
                                                saveRepositories([...repositories, repository])
                                            }
                                        }}
                                    />
                                </div>
                            ) : (
                                <Text size="xs" variant="muted">
                                    {`Up to ${MAX_REPOSITORIES} repositories`}
                                </Text>
                            )}
                        </div>
                    )}
                    {integrationId && !integrationsLoading && !repositories.length && (
                        <Text size="xs" variant="muted">
                            No repositories yet. Sessions start without code checked out.
                        </Text>
                    )}
                    {saving && (
                        <Text size="xs" variant="muted" className="flex items-center gap-1.5">
                            <Spinner aria-hidden />
                            Saving…
                        </Text>
                    )}
                    {saveFailed && !saving && (
                        <Text size="xs" variant="destructive" role="alert">
                            Couldn’t save. Try again.
                        </Text>
                    )}
                </CardContent>
            </Card>
        </SpaceSettingsSection>
    )
}
