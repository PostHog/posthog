import { useValues } from 'kea'
import { useId } from 'react'

import { Badge, Spinner, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

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

import { getOriginProductMeta } from 'products/posthog_ai/frontend/api/taskSource'

import { TaskListItemApi } from '../generated/api.schemas'
import { SpaceFeedSelectCheckbox } from './SpaceFeedSelectCheckbox'
import { spaceFeedStatus } from './spaceFeedStatus'
import { SpaceFeedStatusIcon } from './SpaceFeedStatusIcon'
import { TaskUserAvatar, taskUserName } from './TaskUserAvatar'
import { useSpaceFeedBulkSelection } from './useSpaceFeedBulkSelection'

interface SpaceFeedListRowProps {
    spaceId: string
    task: TaskListItemApi
    pinned: boolean
    unread: boolean
}

/** A session as one compact row of the feed's list view, like PostHog Desktop's. */
export function SpaceFeedListRow({ spaceId, task, pinned, unread }: SpaceFeedListRowProps): JSX.Element {
    const { renaming } = useValues(todaySessionMenuLogic)
    const { user } = useValues(userLogic)
    const { pullRequestStates } = useValues(todaySpacesLogic)
    const item = sessionItem(task)
    const menuId = useId()
    const menu = sessionMenuTarget(item, { menuId, pinned, userId: user?.id })
    const [mainPullRequest] = item.pullRequests
    const status = spaceFeedStatus(task.latest_run, mainPullRequest && pullRequestStates[mainPullRequest.url])
    const author = task.created_by
    const source = getOriginProductMeta(item.originProduct ?? undefined)
    const selection = useSpaceFeedBulkSelection(spaceId)
    const selected = selection.selectedSessionIds.includes(task.id)

    if (renaming?.sessionId === task.id && renaming.surface === 'feed') {
        return (
            <div className="flex h-8 items-center gap-2 px-2">
                <SpaceFeedStatusIcon item={item} />
                <div className="min-w-0 flex-1">
                    <TodaySessionRenameInput sessionId={task.id} title={task.title} />
                </div>
            </div>
        )
    }
    return (
        <>
            <TodaySessionContextMenu target={menu} surface="feed" selection={selection}>
                <div
                    className={cn(
                        'group/row relative flex h-8 w-full items-center gap-2 rounded-md px-2 transition-colors hover:bg-fill-selected has-focus-visible:ring-2 has-focus-visible:ring-ring',
                        selected && 'bg-primary/10 hover:bg-primary/15'
                    )}
                >
                    <SpaceFeedSelectCheckbox
                        spaceId={spaceId}
                        sessionId={task.id}
                        title={item.title || 'Untitled session'}
                    >
                        <SpaceFeedStatusIcon item={item} />
                    </SpaceFeedSelectCheckbox>
                    <LinkPrimitive
                        to={urls.aiTask(task.id)}
                        className="min-w-0 flex-1 truncate text-(length:--text-ui) leading-(--text-ui--line-height) font-medium text-foreground after:absolute after:inset-0"
                        data-attr="today-space-feed-row"
                    >
                        {item.title || 'Untitled session'}
                    </LinkPrimitive>
                    {unread && (
                        <span
                            role="img"
                            aria-label="Unread"
                            className="size-1.5 shrink-0 rounded-full bg-primary"
                            data-attr="today-unread-feed-dot"
                        />
                    )}
                    {source && (
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <span
                                        role="img"
                                        aria-label={`Source: ${source.label}`}
                                        className="relative flex size-3.5 shrink-0 text-muted-foreground [&>svg]:size-full"
                                        data-attr="today-space-feed-source"
                                    />
                                }
                            >
                                {source.icon}
                            </TooltipTrigger>
                            <TooltipContent>{`Source: ${source.label}`}</TooltipContent>
                        </Tooltip>
                    )}
                    {status && (
                        <Badge variant={status.variant} className="shrink-0">
                            {status.running && <Spinner aria-hidden data-icon="inline-start" />}
                            {status.label}
                        </Badge>
                    )}
                    {author && (
                        <span role="img" aria-label={taskUserName(author)} className="relative flex shrink-0">
                            <TaskUserAvatar user={author} />
                        </span>
                    )}
                    {/* The age gives way to the menu on hover, so the row keeps its width. */}
                    {item.timestamp && (
                        <Text
                            render={<span />}
                            size="xs"
                            variant="muted"
                            className="w-8 shrink-0 text-right transition-opacity group-focus-within/row:opacity-0 group-hover/row:opacity-0"
                            translate="no"
                        >
                            {shortTimeAgo(item.timestamp)}
                        </Text>
                    )}
                    <span className="absolute right-1 opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100">
                        <TodaySessionMenu target={menu} surface="feed" />
                    </span>
                </div>
            </TodaySessionContextMenu>
            <TodaySessionDialogs target={menu} />
        </>
    )
}
