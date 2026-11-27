import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'
import { urls } from 'scenes/urls'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'

interface InboxSetupGithubConnectProps {
    /** Shown under the connect button. An empty string leaves it out. */
    connectDescription: string
}

export function InboxSetupGithubConnect({ connectDescription }: InboxSetupGithubConnectProps): JSX.Element {
    const { saving } = useValues(inboxSetupLogic)
    const { connectGithub } = useActions(inboxSetupLogic)
    return (
        <GithubIntegration
            next={combineUrl(urls.inbox(), { onboarding_step: 'github' }).url}
            connectSurface="inbox_welcome"
            onAuthorize={connectGithub}
            authorizing={saving}
            connectText="Connect GitHub"
            emphasizeConnect
            showPersonalConnectionHelp={false}
            showManageButton={false}
            integrationSuffix={<></>}
            connectDescription={connectDescription}
        />
    )
}
