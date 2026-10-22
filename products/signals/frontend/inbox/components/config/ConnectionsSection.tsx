import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconChevronRight, IconGithub } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

export function ConnectionsSection(): JSX.Element {
    const { githubReadiness, integrationsLoading, integrationsLoadFailed } = useValues(integrationsLogic)
    const { loadIntegrations } = useActions(integrationsLogic)

    const isConnected = githubReadiness === 'ready' && !integrationsLoading && !integrationsLoadFailed
    const label = {
        ready: 'Manage',
        not_connected: 'Connect GitHub',
        reconnect_required: 'Reconnect GitHub',
        no_repositories: 'Manage repository access',
        temporarily_unavailable: 'Check connection',
    }[githubReadiness]
    const description = {
        ready: 'Agents can read your repositories and create pull requests.',
        not_connected: 'Connect GitHub to start scouts, research, and implementation in this project.',
        reconnect_required: 'GitHub access is unavailable. Reconnect to resume scouts, research, and implementation.',
        no_repositories: 'Allow access to at least one repository to resume scouts, research, and implementation.',
        temporarily_unavailable:
            'Scouts, research, and implementation are waiting for GitHub access. Check again shortly.',
    }[githubReadiness]

    return (
        <div className="flex flex-wrap items-center justify-between gap-4 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start gap-3 min-w-0">
                <IconGithub className="size-5 shrink-0 mt-0.5 text-default" />
                <div className="min-w-0">
                    <div className="font-medium text-sm text-default flex items-center gap-1.5">
                        GitHub
                        {isConnected && (
                            <span className="inline-flex items-center gap-1 text-xs text-success font-normal">
                                <IconCheckCircle className="size-3.5" />
                                Connected
                            </span>
                        )}
                    </div>
                    <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                        {integrationsLoading
                            ? 'Checking GitHub connection…'
                            : integrationsLoadFailed
                              ? 'Could not load your GitHub connection. Retry to check its status.'
                              : description}
                    </p>
                </div>
            </div>
            <LemonButton
                data-attr="self-driving-github-connection"
                loading={integrationsLoading}
                type="secondary"
                size="small"
                sideIcon={<IconChevronRight />}
                to={
                    integrationsLoadFailed ? undefined : urls.settings('environment-integrations', 'integration-github')
                }
                onClick={integrationsLoadFailed ? () => loadIntegrations() : undefined}
            >
                {integrationsLoadFailed ? 'Retry' : label}
            </LemonButton>
        </div>
    )
}
