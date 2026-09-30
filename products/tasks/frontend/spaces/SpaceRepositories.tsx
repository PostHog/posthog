import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonSnack, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

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
        <div className="flex flex-col gap-2">
            {repositories.length ? (
                <div className="flex flex-wrap gap-1">
                    {repositories.map((repository) => (
                        <LemonSnack
                            key={repository}
                            onClose={
                                savingSpace
                                    ? undefined
                                    : () => updateSpace({ repositories: repositories.filter((r) => r !== repository) })
                            }
                            data-attr="today-space-settings-repository"
                        >
                            {repository}
                        </LemonSnack>
                    ))}
                </div>
            ) : (
                <span className="text-secondary text-sm">No repositories yet.</span>
            )}
            {integrationsLoading ? (
                <Spinner />
            ) : !integrationId ? (
                <LemonButton
                    className="self-start"
                    size="small"
                    type="secondary"
                    icon={<IconGithub />}
                    to={api.integrations.authorizeUrl({ kind: 'github', next: window.location.pathname })}
                    disableClientSideRouting
                    data-attr="today-space-settings-connect-github"
                >
                    Connect GitHub
                </LemonButton>
            ) : repositories.length < MAX_REPOSITORIES ? (
                <div className="max-w-100">
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
                <span className="text-secondary text-sm">A space can have up to {MAX_REPOSITORIES} repositories.</span>
            )}
        </div>
    )
}
