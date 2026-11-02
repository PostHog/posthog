import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'

interface GitHubConnectionNoticeProps {
    className?: string
}

export function GitHubConnectionNotice({ className }: GitHubConnectionNoticeProps): JSX.Element | null {
    const { teamConfigLoading, teamConfigLoadFailed, githubConnectionPresentation } = useValues(signalTeamConfigLogic)
    const { loadTeamConfig } = useActions(signalTeamConfigLogic)

    if (teamConfigLoading || (!teamConfigLoadFailed && !githubConnectionPresentation)) {
        return null
    }
    const retry = teamConfigLoadFailed || githubConnectionPresentation?.retry
    return (
        <LemonBanner
            type={!teamConfigLoadFailed && githubConnectionPresentation?.blocked ? 'warning' : 'info'}
            icon={<IconGithub className="size-5 shrink-0" />}
            className={className}
            action={{
                children: teamConfigLoadFailed ? 'Retry' : githubConnectionPresentation?.action,
                to: retry ? undefined : urls.settings('environment-integrations', 'integration-github'),
                onClick: retry ? () => loadTeamConfig(true) : undefined,
                'data-attr': 'self-driving-github-notice-connect',
            }}
        >
            <h4 className="m-0 text-sm font-semibold">
                {teamConfigLoadFailed ? 'Could not check research access' : githubConnectionPresentation?.title}
            </h4>
            <p className="mt-1 mb-0">
                {teamConfigLoadFailed
                    ? 'Retry to check whether research and GitHub access are available.'
                    : githubConnectionPresentation?.description}
            </p>
        </LemonBanner>
    )
}
