import { useValues } from 'kea'

import { apiHostOrigin } from 'lib/utils/apiHost'
import { getBackendHost } from 'lib/utils/oauthClient'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export interface SendFromCodeTarget {
    projectToken: string | null
    host: string
    appHost: string | null
    sendUrl: string
    secretKeysUrl: string
}

export function useSendFromCodeTarget(): SendFromCodeTarget {
    const { currentTeam, currentTeamIdStrict } = useValues(teamLogic)
    // In OAuth mode this app runs against a remote region, which is where the user's server has to send.
    const appOrigin = getBackendHost() ?? window.location.origin
    const host = apiHostOrigin(appOrigin)
    return {
        projectToken: currentTeam?.api_token ?? null,
        host,
        appHost: host === appOrigin ? host : null,
        sendUrl: `${appOrigin}/api/projects/${currentTeamIdStrict}/messaging/send/email/`,
        secretKeysUrl: new URL(
            urls.project(currentTeamIdStrict, urls.settings('environment-secret-api-keys')),
            appOrigin
        ).href,
    }
}
