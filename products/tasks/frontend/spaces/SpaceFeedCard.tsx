import { useValues } from 'kea'

import { IconGitBranch } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { TodaySessionMenu } from '~/layout/today/TodaySessionMenu'
import { todaySessionMenuLogic } from '~/layout/today/todaySessionMenuLogic'
import { TodaySessionRenameInput } from '~/layout/today/TodaySessionRenameInput'
import { sessionItem, shortTimeAgo } from '~/layout/today/todayWorkItems'

import { TaskListItemApi } from '../generated/api.schemas'
import { spaceFeedStatus } from './spaceFeedStatus'

interface SpaceFeedCardProps {
    task: TaskListItemApi
    pinned: boolean
}

export function SpaceFeedCard({ task, pinned }: SpaceFeedCardProps): JSX.Element {
    const { renaming } = useValues(todaySessionMenuLogic)
    const item = sessionItem(task)
    const status = spaceFeedStatus(task.latest_run)
    const preview = 'description_preview' in task ? task.description_preview : task.description
    const author = task.created_by

    return (
        <article className="TodaySpaceFeed__card">
            <div className="flex items-center gap-2">
                <span className="TodayPaneRow__icon" aria-hidden>
                    <span className="TodayPane__dot" data-kind="session" data-status={item.status ?? undefined} />
                </span>
                {renaming?.sessionId === task.id && renaming.surface === 'feed' ? (
                    <div className="min-w-0 flex-1">
                        <TodaySessionRenameInput sessionId={task.id} title={task.title} />
                    </div>
                ) : (
                    <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
                        <Link
                            to={urls.aiTask(task.id)}
                            subtle
                            className="TodaySpaceFeed__title"
                            data-attr="today-space-feed-card"
                        >
                            {item.title || 'Untitled session'}
                        </Link>
                        {item.timestamp && (
                            <span className="TodaySpaceFeed__muted shrink-0">{`· ${shortTimeAgo(item.timestamp)}`}</span>
                        )}
                    </div>
                )}
                <div className="TodaySpaceFeed__actions">
                    {status && <LemonTag type={status.type}>{status.label}</LemonTag>}
                    <TodaySessionMenu sessionId={task.id} pinned={pinned} spaceId={item.channel} surface="feed" />
                </div>
            </div>
            {preview && <p className="TodaySpaceFeed__muted mt-1.5 mb-0 line-clamp-2 break-words">{preview}</p>}
            {(task.repository || author) && (
                <div className="mt-3 flex min-w-0 items-center gap-2">
                    {task.repository && (
                        <span className="TodaySpaceFeed__muted inline-flex min-w-0 items-center gap-1">
                            <IconGitBranch className="shrink-0" />
                            <span className="truncate">{task.repository}</span>
                        </span>
                    )}
                    {author && (
                        <ProfilePicture
                            user={{ first_name: author.first_name, last_name: author.last_name, email: author.email }}
                            size="sm"
                            className="ml-auto shrink-0"
                        />
                    )}
                </div>
            )}
        </article>
    )
}
