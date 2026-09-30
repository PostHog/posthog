import { useValues } from 'kea'

import { IconGitBranch } from '@posthog/icons'
import { Avatar, AvatarFallback, Badge, Card, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { TodaySessionMenu } from '~/layout/today/TodaySessionMenu'
import { todaySessionMenuLogic } from '~/layout/today/todaySessionMenuLogic'
import { TodaySessionRenameInput } from '~/layout/today/TodaySessionRenameInput'
import { TodaySessionStatusIcon } from '~/layout/today/TodaySessionStatusIcon'
import { analysisRunId, canHandOff, sessionItem, shortTimeAgo } from '~/layout/today/todayWorkItems'

import { TaskListItemApi } from '../generated/api.schemas'
import { spaceFeedStatus } from './spaceFeedStatus'

interface SpaceFeedCardProps {
    task: TaskListItemApi
    pinned: boolean
}

export function SpaceFeedCard({ task, pinned }: SpaceFeedCardProps): JSX.Element {
    const { renaming } = useValues(todaySessionMenuLogic)
    const { user } = useValues(userLogic)
    const item = sessionItem(task)
    const status = spaceFeedStatus(task.latest_run)
    const preview = 'description_preview' in task ? task.description_preview : task.description
    const author = task.created_by
    const authorName = author ? [author.first_name, author.last_name].filter(Boolean).join(' ') || author.email : null
    const initials = authorName
        ? authorName
              .split(/\s+/)
              .slice(0, 2)
              .map((part) => part[0]?.toUpperCase())
              .join('')
        : ''

    return (
        <Card size="sm" className="group/card relative gap-2 px-3 py-3">
            <div className="flex min-w-0 items-center gap-2">
                <TodaySessionStatusIcon item={item} pinned={false} />
                {renaming?.sessionId === task.id && renaming.surface === 'feed' ? (
                    <div className="min-w-0 flex-1">
                        <TodaySessionRenameInput sessionId={task.id} title={task.title} />
                    </div>
                ) : (
                    <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
                        <LinkPrimitive
                            to={urls.aiTask(task.id)}
                            className="min-w-0 truncate font-medium text-foreground after:absolute after:inset-0 hover:underline"
                            data-attr="today-space-feed-card"
                        >
                            {item.title || 'Untitled session'}
                        </LinkPrimitive>
                        {item.timestamp && (
                            <Text render={<span />} size="xs" variant="muted" className="shrink-0" translate="no">
                                {`· ${shortTimeAgo(item.timestamp)}`}
                            </Text>
                        )}
                    </div>
                )}
                <div className="relative flex shrink-0 items-center gap-1">
                    {status && <Badge variant={status.variant}>{status.label}</Badge>}
                    <TodaySessionMenu
                        sessionId={task.id}
                        pinned={pinned}
                        spaceId={item.channel}
                        surface="feed"
                        canHandOff={canHandOff(item, user?.id)}
                        analysisRunId={analysisRunId(item)}
                    />
                </div>
            </div>
            {preview && (
                <Text size="sm" variant="muted" className="line-clamp-2 break-words">
                    {preview}
                </Text>
            )}
            {(task.repository || author) && (
                <div className="flex min-w-0 items-center gap-2 pt-1">
                    {task.repository && (
                        <Text
                            render={<span />}
                            size="xs"
                            variant="muted"
                            className="inline-flex min-w-0 items-center gap-1"
                        >
                            <IconGitBranch className="shrink-0" />
                            <span className="truncate">{task.repository}</span>
                        </Text>
                    )}
                    {authorName && (
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Avatar size="xs" className="relative ml-auto shrink-0" aria-label={authorName} />
                                }
                            >
                                <AvatarFallback>{initials}</AvatarFallback>
                            </TooltipTrigger>
                            <TooltipContent>{authorName}</TooltipContent>
                        </Tooltip>
                    )}
                </div>
            )}
        </Card>
    )
}
