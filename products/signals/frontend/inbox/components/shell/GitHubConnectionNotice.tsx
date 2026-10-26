import { useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'

interface GitHubConnectionNoticeProps {
    className?: string
}

export function GitHubConnectionNotice({ className }: GitHubConnectionNoticeProps): JSX.Element | null {
    const { githubConnectionIssue } = useValues(signalTeamConfigLogic)

    if (!githubConnectionIssue) {
        return null
    }

    const title = {
        not_connected: 'Connect GitHub to continue self-driving',
        reconnect_required: 'Reconnect GitHub to continue self-driving',
        no_repositories: 'Allow repository access to continue self-driving',
    }[githubConnectionIssue]
    const actionLabel = {
        not_connected: 'Connect GitHub',
        reconnect_required: 'Reconnect GitHub',
        no_repositories: 'Manage repository access',
    }[githubConnectionIssue]

    return (
        <LemonBanner
            type="warning"
            icon={<IconGithub className="size-5 shrink-0" />}
            className={className}
            action={{
                children: actionLabel,
                to: urls.settings('environment-integrations', 'integration-github'),
                'data-attr': 'self-driving-github-notice-connect',
            }}
        >
            <h4 className="m-0 text-sm font-semibold">{title}</h4>
            <p className="mt-1 mb-0">
                Self-driving needs access to a GitHub repository to run scouts, research reports, and create pull
                requests.
            </p>
        </LemonBanner>
    )
}
