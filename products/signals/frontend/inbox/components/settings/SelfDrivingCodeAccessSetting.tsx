import { useMountedLogic } from 'kea'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'
import { urls } from 'scenes/urls'

import { RepoRoutingRules } from '../config/RepoRoutingRules'

export function SelfDrivingCodeAccessSetting(): JSX.Element {
    useMountedLogic(integrationsLogic)

    return (
        <div className="flex flex-col gap-3 max-w-4xl">
            {/* The OAuth round trip returns to `next`; land back on this setting so the result is in view. */}
            <GithubIntegration
                next={urls.settings('environment-self-driving', 'self-driving-code-access')}
                connectSurface="signals_agent_setup"
            />
            <RepoRoutingRules />
        </div>
    )
}
