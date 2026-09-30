import { useValues } from 'kea'

import { IconGitBranch } from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    Badge,
    Button,
    Card,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { TodaySessionMenu } from '~/layout/today/TodaySessionMenu'
import { todaySessionMenuLogic } from '~/layout/today/todaySessionMenuLogic'
import { TodaySessionRenameInput } from '~/layout/today/TodaySessionRenameInput'
import { TodaySessionStatusIcon } from '~/layout/today/TodaySessionStatusIcon'
import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { activeCloudRunId, analysisRunId, canHandOff, sessionItem, shortTimeAgo } from '~/layout/today/todayWorkItems'

import { TaskListItemApi } from '../generated/api.schemas'
import { spaceFeedPreview } from './spaceFeedPreview'
import { spaceFeedStatus } from './spaceFeedStatus'
import { TaskPullRequestChip } from './TaskPullRequestChip'
import { pullRequestLabel, splitPullRequests } from './taskPullRequests'

interface SpaceFeedCardProps {
    task: TaskListItemApi
    pinned: boolean
    unread: boolean
}

export function SpaceFeedCard({ task, pinned, unread }: SpaceFeedCardProps): JSX.Element {
    const { renaming } = useValues(todaySessionMenuLogic)
    const { user } = useValues(userLogic)
    const { pullRequestStates } = useValues(todaySpacesLogic)
    const item = sessionItem(task)
    const [mainPullRequest] = item.pullRequests
    const status = spaceFeedStatus(task.latest_run, mainPullRequest && pullRequestStates[mainPullRequest.url])
    const pullRequests = splitPullRequests(item.pullRequests)
    const preview = spaceFeedPreview('description_preview' in task ? task.description_preview : task.description)
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
                            className={cn(
                                'min-w-0 truncate text-foreground after:absolute after:inset-0 hover:underline',
                                unread ? 'font-semibold' : 'font-medium'
                            )}
                            data-attr="today-space-feed-card"
                        >
                            {item.title || 'Untitled session'}
                        </LinkPrimitive>
                        {unread && (
                            <span
                                role="img"
                                aria-label="Unread"
                                className="size-1.5 shrink-0 self-center rounded-full bg-primary"
                                data-attr="today-unread-feed-dot"
                            />
                        )}
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
                        title={item.title}
                        pinned={pinned}
                        spaceId={item.channel}
                        surface="feed"
                        canHandOff={canHandOff(item, user?.id)}
                        analysisRunId={analysisRunId(item)}
                        activeRunId={activeCloudRunId(item)}
                    />
                </div>
            </div>
            {preview && (
                <Text size="sm" variant="muted" className="line-clamp-2 break-words">
                    {preview}
                </Text>
            )}
            {(task.repository || author || item.pullRequests.length > 0) && (
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
                    {pullRequests.visible.map((pullRequest) => (
                        <TaskPullRequestChip
                            key={pullRequest.url}
                            pullRequest={pullRequest}
                            label={pullRequestLabel(pullRequest, task.repository)}
                            state={pullRequestStates[pullRequest.url]}
                            dataAttr="today-pr-chip-feed"
                        />
                    ))}
                    {pullRequests.overflow.length > 0 && (
                        <Popover>
                            <PopoverTrigger
                                render={
                                    <Button
                                        size="xs"
                                        variant="outline"
                                        className="relative shrink-0"
                                        data-attr="today-pr-chip-overflow"
                                    />
                                }
                            >
                                {`+${pullRequests.overflow.length} ${pullRequests.overflow.length === 1 ? 'PR' : 'PRs'}`}
                            </PopoverTrigger>
                            <PopoverContent align="start" className="flex max-w-72 flex-col items-start gap-1">
                                {pullRequests.overflow.map((pullRequest) => (
                                    <TaskPullRequestChip
                                        key={pullRequest.url}
                                        pullRequest={pullRequest}
                                        label={pullRequestLabel(pullRequest, task.repository)}
                                        state={pullRequestStates[pullRequest.url]}
                                        dataAttr="today-pr-chip-feed"
                                    />
                                ))}
                            </PopoverContent>
                        </Popover>
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
