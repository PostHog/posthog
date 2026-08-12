import { useMountedLogic, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'

interface ScoutGitHubConnectionProps {
    githubSetupNextUrl?: string
}

export function ScoutGitHubConnection({ githubSetupNextUrl }: ScoutGitHubConnectionProps): JSX.Element | null {
    useMountedLogic(integrationsLogic)
    const { githubIntegrations, integrations, integrationsLoading } = useValues(integrationsLogic)

    if (githubIntegrations.length > 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-3 rounded border border-primary bg-surface-secondary p-3">
            <div className="flex min-w-0 items-start gap-2.5">
                <IconGithub className="mt-0.5 size-4 shrink-0 text-secondary" />
                <div className="flex min-w-0 flex-col">
                    <span className="font-medium text-sm">GitHub connection</span>
                    <span className="text-xs text-muted">
                        Connect GitHub so Self-driving can read code and open pull requests for actionable findings.
                    </span>
                </div>
            </div>
            {integrations === null || integrationsLoading ? (
                <span className="text-xs text-muted">Loading GitHub connections…</span>
            ) : (
                <GithubIntegration next={githubSetupNextUrl} />
            )}
        </div>
    )
}
