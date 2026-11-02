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
    const presentation = teamConfigLoadFailed
        ? {
              blocked: false,
              retry: true,
              action: 'Retry',
              title: 'Could not check research access',
              description: 'Retry to check whether research and GitHub access are available.',
          }
        : githubConnectionPresentation

    if (teamConfigLoading || !presentation) {
        return null
    }
    return (
        <LemonBanner
            type={presentation.blocked ? 'warning' : 'info'}
            icon={<IconGithub className="size-5 shrink-0" />}
            className={className}
            action={{
                children: presentation.action,
                to: presentation.retry ? undefined : urls.settings('environment-integrations', 'integration-github'),
                onClick: presentation.retry ? () => loadTeamConfig(true) : undefined,
                'data-attr': 'self-driving-github-notice-connect',
            }}
        >
            <h4 className="m-0 text-sm font-semibold">{presentation.title}</h4>
            <p className="mt-1 mb-0">{presentation.description}</p>
        </LemonBanner>
    )
}
