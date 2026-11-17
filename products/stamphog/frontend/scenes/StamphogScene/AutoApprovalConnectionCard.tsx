import { useActions, useValues } from 'kea'

import { IconGithub, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { GitHubAccountCard } from 'lib/components/RepositoryList/GitHubAccountCard'

import { stamphogSceneLogic } from './stamphogSceneLogic'

export function AutoApprovalConnectionCard(): JSX.Element {
    const {
        hasInstallation,
        availableRepositoriesFailed,
        openingInstallPage,
        refreshingFromGitHub,
        connectDisabledReason,
        githubAccountNames,
        reachableRepositoryCount,
    } = useValues(stamphogSceneLogic)
    const { openInstallPage, refreshFromGitHub, loadAvailableRepositories } = useActions(stamphogSceneLogic)

    if (hasInstallation === null) {
        if (availableRepositoriesFailed) {
            return (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadAvailableRepositories({ search: '' }) }}
                    data-attr="stamphog-available-repositories-error"
                >
                    Could not check the GitHub connection. Try again.
                </LemonBanner>
            )
        }
        return <LemonSkeleton className="h-14 w-full" />
    }

    if (!hasInstallation) {
        return (
            <GitHubAccountCard
                title={<span className="text-sm font-semibold">Install the Stamphog app on GitHub</span>}
                hint="Auto-approval reviews pull requests through this app. Install it on your organization, then add the repositories to approve."
                actions={
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconGithub />}
                        onClick={openInstallPage}
                        loading={openingInstallPage}
                        disabledReason={connectDisabledReason}
                        data-attr="stamphog-connect-repository"
                    >
                        Connect GitHub
                    </LemonButton>
                }
            />
        )
    }

    return (
        <GitHubAccountCard
            title={
                <span className="text-sm">
                    <span className="font-semibold">
                        {githubAccountNames.length > 0 ? githubAccountNames.join(', ') : 'GitHub'}
                    </span>
                    {reachableRepositoryCount !== null && (
                        <span className="text-secondary">
                            {` · Stamphog app installed on ${reachableRepositoryCount} ${reachableRepositoryCount === 1 ? 'repository' : 'repositories'}`}
                        </span>
                    )}
                </span>
            }
            hint="Missing a repository? An admin of your GitHub organization can give the Stamphog app access to it."
            actions={
                <>
                    <LemonButton
                        size="small"
                        type="tertiary"
                        icon={<IconGithub />}
                        onClick={openInstallPage}
                        loading={openingInstallPage}
                        disabledReason={connectDisabledReason}
                        data-attr="stamphog-grant-repository-access"
                    >
                        Grant access on GitHub
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="tertiary"
                        icon={<IconRefresh />}
                        onClick={refreshFromGitHub}
                        loading={refreshingFromGitHub}
                        disabledReason={connectDisabledReason}
                        tooltip="Checks GitHub again for the repositories you can reach"
                        data-attr="stamphog-refresh-repositories"
                    >
                        Refresh the list
                    </LemonButton>
                </>
            }
        />
    )
}
