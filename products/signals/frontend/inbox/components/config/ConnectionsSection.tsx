import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconChevronRight, IconGithub } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'

export function ConnectionsSection(): JSX.Element {
    const { teamConfig, teamConfigLoading, teamConfigLoadFailed, githubConnectionPresentation } =
        useValues(signalTeamConfigLogic)
    const { loadTeamConfig } = useActions(signalTeamConfigLogic)
    const isConnected = teamConfig?.github_readiness === 'ready' && !teamConfigLoading && !teamConfigLoadFailed
    const retry = teamConfigLoadFailed || githubConnectionPresentation?.retry

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
                        {teamConfigLoading
                            ? 'Checking GitHub access…'
                            : teamConfigLoadFailed
                              ? 'Could not check GitHub access. Retry to check its status.'
                              : (githubConnectionPresentation?.description ??
                                'Agents can read your repositories and create pull requests with your permission.')}
                    </p>
                </div>
            </div>
            <LemonButton
                type="secondary"
                size="small"
                sideIcon={<IconChevronRight />}
                loading={teamConfigLoading}
                data-attr="self-driving-github-connection"
                to={retry ? undefined : urls.settings('environment-integrations', 'integration-github')}
                onClick={retry ? () => loadTeamConfig(true) : undefined}
            >
                {teamConfigLoadFailed ? 'Retry' : (githubConnectionPresentation?.action ?? 'Manage')}
            </LemonButton>
        </div>
    )
}
