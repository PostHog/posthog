import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { ErrorTrackingAlertThreadApi } from '../../../generated/api.schemas'
import { issueAlertThreadsLogic } from './issueAlertThreadsLogic'

function ThreadRow({ thread }: { thread: ErrorTrackingAlertThreadApi }): JSX.Element {
    const channel = thread.channel_name || thread.channel || 'Slack'
    const failing = thread.consecutive_failures > 0
    return (
        <div className="flex flex-col gap-0.5 py-1">
            <div className="flex items-center justify-between gap-2">
                {thread.external_url ? (
                    <Link to={thread.external_url} target="_blank" className="font-medium truncate">
                        {channel}
                        <IconExternal className="ml-1 inline-block text-xs" />
                    </Link>
                ) : (
                    <span className="font-medium truncate">{channel}</span>
                )}
                {failing && (
                    <LemonTag type="danger" size="small">
                        Failed
                    </LemonTag>
                )}
            </div>
            <div className="text-xs text-secondary">
                {failing ? (
                    thread.last_error || 'Delivery failed'
                ) : thread.external_url ? (
                    <>
                        Opened by {thread.alert_name} · updated <TZLabel time={thread.updated_at} />
                    </>
                ) : (
                    <>Not posted yet by {thread.alert_name}</>
                )}
            </div>
        </div>
    )
}

export function IssueNotifications({ issueId }: { issueId: string }): JSX.Element | null {
    const { threads, threadsLoading, threadsLoaded, loadError } = useValues(issueAlertThreadsLogic({ issueId }))
    const { loadThreads } = useActions(issueAlertThreadsLogic({ issueId }))

    return (
        <ScenePanelLabel title="Notifications">
            <div className="flex flex-col divide-y">
                {loadError ? (
                    <span className="text-xs text-secondary py-1">
                        Could not load Slack threads. <Link onClick={loadThreads}>Retry</Link>
                    </span>
                ) : threadsLoading && !threadsLoaded ? (
                    <Spinner className="my-1" />
                ) : threadsLoaded && threads.length === 0 ? (
                    <span className="text-xs text-secondary py-1">
                        No Slack threads for this issue.{' '}
                        <Link to={urls.settings('environment-error-tracking', 'error-tracking-alerting')}>
                            Manage alerts
                        </Link>
                    </span>
                ) : (
                    threads.map((thread) => <ThreadRow key={thread.id} thread={thread} />)
                )}
            </div>
        </ScenePanelLabel>
    )
}
