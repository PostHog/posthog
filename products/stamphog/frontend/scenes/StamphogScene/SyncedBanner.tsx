import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { stamphogSceneLogic } from './stamphogSceneLogic'

export function SyncedBanner(): JSX.Element | null {
    const { syncResult, skippedRepos, appNotInstalled, installUrl, discoveredInstallations } =
        useValues(stamphogSceneLogic)
    const { connectInstallation } = useActions(stamphogSceneLogic)

    // Discovery found several installations and bound nothing: the user picks which one this team
    // connects. The pick rides sessionStorage through one more (silent) authorize hop, and the
    // backend's explicit-id path verifies it.
    if (discoveredInstallations.length > 0) {
        return (
            <LemonBanner type="info">
                <p className="font-medium">The Stamphog app is installed on several GitHub accounts</p>
                <p>Pick the one to connect to this project:</p>
                <div className="flex flex-wrap gap-2">
                    {discoveredInstallations.map((installation) => (
                        <LemonButton
                            key={installation.id}
                            type="secondary"
                            icon={<IconGithub />}
                            onClick={() => connectInstallation(installation.id)}
                        >
                            {installation.account_login}
                        </LemonButton>
                    ))}
                </div>
            </LemonBanner>
        )
    }

    // Discovery found no installation the user can reach: they authorized the App but never installed it
    // on the org. Point them at the GitHub install page (install_url still carries a fresh state token).
    if (appNotInstalled) {
        return (
            <LemonBanner type="warning">
                <p className="font-medium">The Stamphog app isn't installed on GitHub yet</p>
                <p>
                    Install the Stamphog app on your GitHub organization to connect its repositories.
                    {installUrl && (
                        <>
                            {' '}
                            <Link to={installUrl} target="_blank" disableClientSideRouting>
                                Install on GitHub
                            </Link>
                        </>
                    )}
                </p>
            </LemonBanner>
        )
    }

    if (!syncResult) {
        return null
    }

    // A sync only makes repositories available to add and turns no reviews on, so the banner says so.
    const availableCount = syncResult.available_count
    return (
        <LemonBanner type={skippedRepos.length > 0 ? 'warning' : 'success'}>
            <p className="font-medium">GitHub is connected</p>
            <p>
                {availableCount === 0
                    ? 'There are no new repositories to add.'
                    : availableCount === 1
                      ? 'You can now add 1 repository. Auto-approval starts once you add it.'
                      : `You can now add ${availableCount} repositories. Auto-approval starts for each one you add.`}
            </p>
            {skippedRepos.length > 0 && (
                <p className="mt-2">
                    {`Skipped ${skippedRepos.join(', ')} because another project already uses ${skippedRepos.length === 1 ? 'it' : 'them'} with this GitHub installation.`}
                </p>
            )}
        </LemonBanner>
    )
}
