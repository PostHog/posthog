import { useValues } from 'kea'
import { useId } from 'react'

import { IconGitBranch } from '@posthog/icons'
import {
    Badge,
    Card,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Spinner,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    badgeVariants,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { TodaySessionContextMenu } from '~/layout/today/TodaySessionContextMenu'
import { TodaySessionDialogs } from '~/layout/today/TodaySessionDialogs'
import { TodaySessionMenu } from '~/layout/today/TodaySessionMenu'
import { todaySessionMenuLogic } from '~/layout/today/todaySessionMenuLogic'
import { TodaySessionRenameInput } from '~/layout/today/TodaySessionRenameInput'
import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { sessionItem, sessionMenuTarget, shortTimeAgo } from '~/layout/today/todayWorkItems'

import { TaskListItemApi } from '../generated/api.schemas'
import { spaceFeedPreview } from './spaceFeedPreview'
import { spaceFeedStatus } from './spaceFeedStatus'
import { SpaceFeedStatusIcon } from './SpaceFeedStatusIcon'
import { TASK_CHIP_CLASS, TaskPullRequestChip } from './TaskPullRequestChip'
import { pullRequestLabel, splitPullRequests } from './taskPullRequests'
import { TaskUserAvatar, taskUserName } from './TaskUserAvatar'

interface SpaceFeedCardProps {
    task: TaskListItemApi
    pinned: boolean
    unread: boolean
    /** The repository to name on the card, or `null` when it is the space's usual one. */
    repository: string | null
}

export function SpaceFeedCard({ task, pinned, unread, repository }: SpaceFeedCardProps): JSX.Element {
    const { renaming } = useValues(todaySessionMenuLogic)
    const { user } = useValues(userLogic)
    const { pullRequestStates } = useValues(todaySpacesLogic)
    const menuId = useId()
    const item = sessionItem(task)
    // The "…" menu and the right-click menu share one menu id, so either one opens the same dialogs.
    const menu = sessionMenuTarget(item, { menuId, pinned, userId: user?.id })
    const [mainPullRequest] = item.pullRequests
    const status = spaceFeedStatus(task.latest_run, mainPullRequest && pullRequestStates[mainPullRequest.url])
    const pullRequests = splitPullRequests(item.pullRequests)
    const preview = spaceFeedPreview('description_preview' in task ? task.description_preview : task.description)
    const author = task.created_by
    const authorName = author ? taskUserName(author) : null

    const card = (
        <Card
            size="sm"
            className="group/card relative my-1.5 gap-0 rounded-xl px-4 pt-3.5 pb-3 transition-colors hover:bg-muted"
        >
            <div className="flex min-w-0 items-center gap-3">
                {renaming?.sessionId === task.id && renaming.surface === 'feed' ? (
                    <div className="flex min-w-0 flex-1 items-center gap-1.5">
                        <SpaceFeedStatusIcon item={item} />
                        <div className="min-w-0 flex-1">
                            <TodaySessionRenameInput sessionId={task.id} title={task.title} />
                        </div>
                    </div>
                ) : (
                    <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
                        {/* Nudged down so the icon sits on the title's baseline, like PostHog Desktop's feed cards. */}
                        <SpaceFeedStatusIcon item={item} className="translate-y-0.5" />
                        <LinkPrimitive
                            to={urls.aiTask(task.id)}
                            className="min-w-0 truncate text-sm leading-snug font-semibold text-foreground after:absolute after:inset-0 hover:underline"
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
                    {status && (
                        <Badge variant={status.variant}>
                            {status.running && <Spinner aria-hidden data-icon="inline-start" />}
                            {status.label}
                        </Badge>
                    )}
                    <TodaySessionMenu target={menu} surface="feed" />
                </div>
            </div>
            {preview && (
                <Text size="xs" variant="muted" className="mt-1.5 line-clamp-2 leading-normal break-words">
                    {preview}
                </Text>
            )}
            {(repository || author || item.pullRequests.length > 0) && (
                <div className="mt-3 flex min-w-0 flex-wrap items-center gap-1.5">
                    {repository && (
                        <Badge
                            className={cn(
                                TASK_CHIP_CLASS,
                                'min-w-0 border-transparent bg-transparent text-muted-foreground'
                            )}
                        >
                            <IconGitBranch className="size-3 shrink-0" />
                            <span className="min-w-0 truncate">{repository}</span>
                        </Badge>
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
                                className={cn(
                                    badgeVariants(),
                                    TASK_CHIP_CLASS,
                                    'border-dashed border-border bg-fill-hover text-muted-foreground hover:bg-fill-selected hover:text-foreground'
                                )}
                                data-attr="today-pr-chip-overflow"
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
                    {author && authorName && (
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <span
                                        role="img"
                                        aria-label={authorName}
                                        className="relative ml-auto flex shrink-0"
                                    />
                                }
                            >
                                <TaskUserAvatar user={author} />
                            </TooltipTrigger>
                            <TooltipContent>{authorName}</TooltipContent>
                        </Tooltip>
                    )}
                </div>
            )}
        </Card>
    )
    // The dialogs sit outside the right-click area, so a right-click inside one does not reach the card's menu.
    return (
        <>
            <TodaySessionContextMenu target={menu} surface="feed">
                {card}
            </TodaySessionContextMenu>
            <TodaySessionDialogs target={menu} />
        </>
    )
}
