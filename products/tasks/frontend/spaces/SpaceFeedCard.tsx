import { useActions, useValues } from 'kea'
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

import { artifactPreviewKind } from 'products/posthog_ai/frontend/api/taskArtifacts'
import { getOriginProductMeta } from 'products/posthog_ai/frontend/api/taskSource'

import { TaskListItemApi } from '../generated/api.schemas'
import { SpaceFeedCardPrompt } from './SpaceFeedCardPrompt'
import { spaceFeedPreview } from './spaceFeedPreview'
import { SpaceFeedSelectCheckbox } from './SpaceFeedSelectCheckbox'
import { spaceFeedStatus } from './spaceFeedStatus'
import { SpaceFeedStatusIcon } from './SpaceFeedStatusIcon'
import { spaceSceneLogic } from './spaceSceneLogic'
import { TaskFileChip } from './TaskFileChip'
import { TaskFile, VISIBLE_FILE_COUNT, taskFiles } from './taskFiles'
import { TASK_CHIP_CLASS, TaskPullRequestChip } from './TaskPullRequestChip'
import { pullRequestLabel, splitPullRequests } from './taskPullRequests'
import { TaskUserAvatar, taskUserName } from './TaskUserAvatar'
import { useSpaceFeedBulkSelection } from './useSpaceFeedBulkSelection'

interface SpaceFeedCardProps {
    spaceId: string
    task: TaskListItemApi
    pinned: boolean
    unread: boolean
    /** The repository to name on the card, or `null` when it is the space's usual one. */
    repository: string | null
}

export function SpaceFeedCard({ spaceId, task, pinned, unread, repository }: SpaceFeedCardProps): JSX.Element {
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
    const { reportArtifactChipClicked } = useActions(spaceSceneLogic({ id: spaceId }))
    const files = taskFiles(task.id, task.latest_run)
    const fileChip = (taskFile: TaskFile, inOverflow: boolean): JSX.Element => (
        <TaskFileChip
            key={taskFile.file.key}
            taskFile={taskFile}
            onOpen={() =>
                reportArtifactChipClicked(artifactPreviewKind(taskFile.file.latest), inOverflow, files.length)
            }
        />
    )
    const hiddenFiles = files.slice(VISIBLE_FILE_COUNT)
    const preview = spaceFeedPreview('description_preview' in task ? task.description_preview : task.description)
    const author = task.created_by
    const authorName = author ? taskUserName(author) : null
    const source = getOriginProductMeta(item.originProduct ?? undefined)
    const selection = useSpaceFeedBulkSelection(spaceId)
    const selected = selection.selectedSessionIds.includes(task.id)

    const card = (
        <Card
            size="sm"
            className={cn(
                'group/card relative my-1.5 gap-0 rounded-xl px-4 pt-3.5 pb-3 transition-colors hover:bg-fill-hover has-focus-visible:ring-2 has-focus-visible:ring-ring',
                selected && 'bg-primary/10 hover:bg-primary/15'
            )}
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
                        <SpaceFeedSelectCheckbox
                            spaceId={spaceId}
                            sessionId={task.id}
                            title={item.title || 'Untitled session'}
                            className="translate-y-0.5"
                        >
                            <SpaceFeedStatusIcon item={item} />
                        </SpaceFeedSelectCheckbox>
                        <LinkPrimitive
                            to={urls.aiTask(task.id)}
                            className="min-w-0 truncate text-sm leading-snug font-semibold text-foreground after:absolute after:inset-0"
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
            <SpaceFeedCardPrompt taskId={task.id} prompt={preview} />
            {(source || repository || author || item.pullRequests.length > 0 || files.length > 0) && (
                <div className="mt-3 flex min-w-0 flex-wrap items-center gap-1.5">
                    {source && (
                        <Badge
                            // No padding: the chip has no fill, so it lines up with the prompt text above it.
                            className={cn(
                                TASK_CHIP_CLASS,
                                'border-transparent bg-transparent px-0 text-muted-foreground'
                            )}
                            data-attr="today-space-feed-source"
                        >
                            <span className="flex size-3 shrink-0 [&>svg]:size-full">{source.icon}</span>
                            {source.label}
                        </Badge>
                    )}
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
                    {files.slice(0, VISIBLE_FILE_COUNT).map((taskFile) => fileChip(taskFile, false))}
                    {hiddenFiles.length > 0 && (
                        <Popover>
                            <PopoverTrigger
                                className={cn(
                                    badgeVariants(),
                                    TASK_CHIP_CLASS,
                                    'border-dashed border-border bg-fill-hover text-muted-foreground hover:bg-fill-selected hover:text-foreground'
                                )}
                                data-attr="today-file-chip-overflow"
                            >
                                {`+${hiddenFiles.length} ${hiddenFiles.length === 1 ? 'file' : 'files'}`}
                            </PopoverTrigger>
                            <PopoverContent align="start" className="flex max-w-72 flex-col items-start gap-1">
                                {hiddenFiles.map((taskFile) => fileChip(taskFile, true))}
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
            <TodaySessionContextMenu target={menu} surface="feed" selection={selection}>
                {card}
            </TodaySessionContextMenu>
            <TodaySessionDialogs target={menu} />
        </>
    )
}
