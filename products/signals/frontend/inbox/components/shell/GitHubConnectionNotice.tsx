import { useValues } from 'kea'
import { useEffect } from 'react'

import { IconGithub, IconPerson } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { useIntegrationManagementRestriction } from 'lib/integrations/integrationPermissions'
import { urls } from 'scenes/urls'

import { captureInboxGithubNoticeViewed } from '../../inboxAnalytics'
import type { GitHubAccessBlocker } from '../../logics/githubConnectionPresentation'
import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'

interface GitHubConnectionNoticeProps {
    /** Null while the list is loading, or when filters hide every report. */
    hasReports: boolean | null
}

interface BlockerCopy {
    cause: string
    action: string
    askAdmin: string
}

const BLOCKER_COPY: Record<GitHubAccessBlocker, BlockerCopy> = {
    not_connected: {
        cause: 'GitHub isn’t connected to this project. Self-driving needs a repository to research issues and open pull requests, so new investigations are on hold.',
        action: 'Connect GitHub',
        askAdmin: 'Ask a project admin to connect GitHub.',
    },
    reconnect_required: {
        cause: 'The GitHub connection for this project stopped working, so self-driving can’t read your code. New investigations are on hold until it’s reconnected.',
        action: 'Reconnect GitHub',
        askAdmin: 'Ask a project admin to reconnect GitHub.',
    },
    no_repositories: {
        cause: 'GitHub is connected, but the PostHog app can’t access any repository. Self-driving needs at least one to research issues and open pull requests, so new investigations are on hold.',
        action: 'Grant repository access',
        askAdmin: 'Ask a project admin to give the PostHog GitHub app access to a repository.',
    },
}

export function GitHubConnectionNotice({ hasReports }: GitHubConnectionNoticeProps): JSX.Element | null {
    const { githubAccessBlocker } = useValues(signalTeamConfigLogic)
    const canManageIntegrations = useIntegrationManagementRestriction() === null

    useEffect(() => {
        if (githubAccessBlocker) {
            captureInboxGithubNoticeViewed({ blocker: githubAccessBlocker, canManageIntegrations })
        }
    }, [githubAccessBlocker, canManageIntegrations])

    if (!githubAccessBlocker) {
        return null
    }
    const copy = BLOCKER_COPY[githubAccessBlocker]
    const reportsLine =
        hasReports === true
            ? ' Your existing reports are below and still work.'
            : hasReports === false
              ? ' New reports will show up here once self-driving is running again.'
              : ''

    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col gap-3 border-warning"
            data-attr="self-driving-github-notice"
        >
            <div className="flex items-center gap-2.5">
                <span className="flex size-8 shrink-0 items-center justify-center rounded bg-fill-warning-highlight text-warning">
                    <IconGithub className="size-5" />
                </span>
                <h3 className="m-0 text-base">Self-driving is paused</h3>
            </div>
            <p className="m-0 max-w-prose text-sm text-secondary">
                {copy.cause}
                {reportsLine}
            </p>
            {canManageIntegrations ? (
                <LemonButton
                    type="primary"
                    size="small"
                    className="w-fit"
                    to={urls.settings('environment-integrations', 'integration-github')}
                    data-attr="self-driving-github-notice-connect"
                >
                    {copy.action}
                </LemonButton>
            ) : (
                <div className="flex w-fit max-w-full items-start gap-2 rounded border bg-surface-secondary px-3 py-2 text-sm font-medium">
                    <IconPerson className="mt-0.5 size-4 shrink-0 text-secondary" />
                    <span>{copy.askAdmin}</span>
                </div>
            )}
        </LemonCard>
    )
}
