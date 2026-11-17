import { useActions, useValues } from 'kea'

import { IconGithub, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { stamphogSceneLogic } from './stamphogSceneLogic'

// The same card shape as the GitHub connection of Code review, so both connections read alike.
const CARD_CLASS = 'flex flex-wrap items-center gap-3 rounded border border-primary bg-surface-primary px-4 py-2.5'

/** Whether the Stamphog GitHub app is connected to this project, with the way to connect it or to reach more repositories. */
export function AutoApprovalConnectionCard(): JSX.Element {
    const {
        hasInstallation,
        availableRepositoriesFailed,
        openingInstallPage,
        refreshingFromGitHub,
        connectDisabledReason,
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
            <div className={CARD_CLASS}>
                <IconGithub className="size-6 shrink-0" />
                <div className="flex min-w-0 flex-1 basis-72 flex-col gap-0.5">
                    <span className="text-sm font-semibold">Install the Stamphog app on GitHub</span>
                    <span className="text-xs text-secondary">
                        Auto-approval reviews pull requests through this app. Install it on your organization, then add
                        the repositories to approve.
                    </span>
                </div>
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
            </div>
        )
    }

    return (
        <div className={CARD_CLASS}>
            <IconGithub className="size-6 shrink-0" />
            <div className="flex min-w-0 flex-1 basis-72 flex-col gap-0.5">
                <span className="text-sm font-semibold">Stamphog app connected</span>
                <span className="text-xs text-secondary">
                    Missing a repository? An admin of your GitHub organization can give the app access to it.
                </span>
            </div>
            <div className="flex flex-wrap items-center gap-1">
                <LemonButton
                    size="small"
                    type="secondary"
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
            </div>
        </div>
    )
}
