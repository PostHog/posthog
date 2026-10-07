import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconComment, IconPin, IconWarning } from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    Badge,
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Separator,
    Skeleton,
    SkeletonText,
    Switch,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill-primitives'

import { dayjs } from 'lib/dayjs'
import { fullNameOrEmail } from 'lib/utils/strings'

import { TaskUserAvatar } from 'products/tasks/frontend/spaces/TaskUserAvatar'

import { ArtifactCommentThread, supportsSelectionComments } from '../artifactComments'
import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { taskRunArtifactsLogic } from '../taskRunArtifactsLogic'
import { ArtifactCommentComposer } from './ArtifactCommentComposer'
import { ArtifactCommentThreadCard } from './ArtifactCommentThreadCard'

function emptyHint(kind: TaskArtifactCommentsLogicProps['kind']): string {
    if (kind === 'image') {
        return 'Comment on the whole image, or pin a comment to a spot on it.'
    }
    if (supportsSelectionComments(kind)) {
        return 'Comment on the whole file, or select text in the preview to comment on it.'
    }
    return 'Comment on the whole file.'
}

function AnchoredThreadRow({ thread, onOpen }: { thread: ArtifactCommentThread; onOpen: () => void }): JSX.Element {
    const name = thread.root.created_by ? fullNameOrEmail(thread.root.created_by) : 'Deleted user'
    const { anchor } = thread
    return (
        <button
            type="button"
            className="flex w-full min-w-0 cursor-pointer gap-2 rounded-md px-2 py-2 text-left hover:bg-fill-hover focus-visible:bg-fill-hover focus-visible:outline-none"
            onClick={onOpen}
            data-attr="task-artifact-comments-menu-thread"
        >
            {thread.root.created_by ? (
                <TaskUserAvatar
                    className="shrink-0"
                    user={{
                        uuid: thread.root.created_by.uuid,
                        email: thread.root.created_by.email,
                        first_name: thread.root.created_by.first_name ?? '',
                        last_name: thread.root.created_by.last_name ?? '',
                    }}
                />
            ) : (
                <Avatar size="xs" className="shrink-0">
                    <AvatarFallback>?</AvatarFallback>
                </Avatar>
            )}
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="flex min-w-0 items-baseline gap-1.5">
                    <Text size="xs" weight="medium" className="truncate" render={<span />}>
                        {name}
                    </Text>
                    <Text size="xxs" variant="muted" className="shrink-0" render={<span />}>
                        {dayjs(thread.root.created_at).fromNow()}
                    </Text>
                </span>
                {anchor?.kind === 'text' && (
                    <Text
                        size="xs"
                        variant="muted"
                        render={<span />}
                        className="line-clamp-1 border-l-2 border-warning pl-1.5 italic"
                    >
                        {anchor.quote}
                    </Text>
                )}
                <Text size="xs" render={<span />} className="line-clamp-2 break-words">
                    {thread.root.content}
                </Text>
                {(thread.pinNumber || thread.resolved || thread.replies.length > 0) && (
                    <span className="flex flex-wrap items-center gap-1">
                        {thread.pinNumber && (
                            <Badge variant="info">
                                <IconPin />
                                {`Pin ${thread.pinNumber}`}
                            </Badge>
                        )}
                        {thread.resolved && <Badge variant="completed">Resolved</Badge>}
                        {thread.replies.length > 0 && (
                            <Text size="xxs" variant="muted" render={<span />}>
                                {thread.replies.length === 1 ? '1 reply' : `${thread.replies.length} replies`}
                            </Text>
                        )}
                    </span>
                )}
            </span>
        </button>
    )
}

export function ArtifactCommentThreadList({
    logicProps,
    cardsOnly = false,
}: {
    logicProps: TaskArtifactCommentsLogicProps
    cardsOnly?: boolean
}): JSX.Element {
    const { visibleThreads, threads, commentsLoadFailed, commentsLoading } = useValues(
        taskArtifactCommentsLogic(logicProps)
    )
    const { loadComments, activateThread } = useActions(taskArtifactCommentsLogic(logicProps))
    const { setCommentsOpen } = useActions(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    if (!threads) {
        if (commentsLoadFailed) {
            return (
                <Empty className="border-0">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconWarning />
                        </EmptyMedia>
                        <EmptyTitle>Comments didn't load</EmptyTitle>
                        <EmptyDescription>Check your connection and try again.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            loading={commentsLoading}
                            onClick={() => loadComments()}
                            data-attr="task-artifact-comments-retry"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        return (
            <div className="flex flex-col gap-4 p-3">
                {[0, 1].map((index) => (
                    <div key={index} className="flex gap-2">
                        <Skeleton className="size-6 shrink-0 rounded-full" />
                        <SkeletonText lines={2} className="flex-1" />
                    </div>
                ))}
            </div>
        )
    }
    if (!visibleThreads || visibleThreads.length === 0) {
        return (
            <Empty className="border-0">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconComment />
                    </EmptyMedia>
                    <EmptyTitle>{threads.length > 0 ? 'No open comments' : 'No comments yet'}</EmptyTitle>
                    <EmptyDescription>
                        {cardsOnly
                            ? 'To add a comment, open this file on a larger screen.'
                            : emptyHint(logicProps.kind)}
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }
    return (
        <div className="flex min-h-0 flex-col gap-1 overflow-y-auto p-1">
            {visibleThreads.map((thread, index) => (
                <Fragment key={thread.root.id}>
                    {index > 0 && <Separator />}
                    {!cardsOnly && thread.anchor && thread.anchor.kind !== 'document' ? (
                        <AnchoredThreadRow
                            thread={thread}
                            onOpen={() => {
                                setCommentsOpen(false)
                                activateThread(thread.root.id, 'menu')
                            }}
                        />
                    ) : (
                        <ArtifactCommentThreadCard logicProps={logicProps} thread={thread} />
                    )}
                </Fragment>
            ))}
        </div>
    )
}

export function ArtifactCommentsMenu({ logicProps }: { logicProps: TaskArtifactCommentsLogicProps }): JSX.Element {
    const { openCount, resolvedCount, showResolved, drafts, writing } = useValues(taskArtifactCommentsLogic(logicProps))
    const { setShowResolved, setDraft, submitComment } = useActions(taskArtifactCommentsLogic(logicProps))
    const { commentsOpen } = useValues(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    const { setCommentsOpen } = useActions(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    const label = openCount > 0 ? `Comments, ${openCount} open` : 'Comments'
    const switchId = `task-artifact-comments-show-resolved-${logicProps.artifactId}`
    return (
        <Popover open={commentsOpen} onOpenChange={(open: boolean) => setCommentsOpen(open)}>
            <Tooltip>
                <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                    <PopoverTrigger
                        render={
                            <Button
                                aria-label={label}
                                className={cn(commentsOpen && 'bg-fill-selected')}
                                data-attr="task-artifact-comments-toggle"
                            />
                        }
                    >
                        <IconComment />
                        {openCount > 0 && (
                            <Text size="xs" render={<span />} className="tabular-nums">
                                {openCount}
                            </Text>
                        )}
                    </PopoverTrigger>
                </TooltipTrigger>
                <TooltipContent>Comments</TooltipContent>
            </Tooltip>
            <PopoverContent
                align="end"
                className="max-h-[min(560px,var(--available-height))] w-80 gap-0 overflow-hidden p-0"
                data-attr="task-artifact-comments-menu"
            >
                <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
                    <Text size="xs" weight="medium" variant="muted" render={<span />}>
                        Comments
                    </Text>
                    {resolvedCount > 0 && (
                        <div className="ml-auto flex items-center gap-2">
                            <Switch
                                id={switchId}
                                size="sm"
                                checked={showResolved}
                                onCheckedChange={(checked: boolean) => setShowResolved(checked)}
                                data-attr="task-artifact-comments-show-resolved"
                            />
                            <Label htmlFor={switchId} className="text-xs">
                                {`Show resolved (${resolvedCount})`}
                            </Label>
                        </div>
                    )}
                </div>
                <div className="shrink-0 border-b border-border p-2">
                    <ArtifactCommentComposer
                        value={drafts.document ?? ''}
                        onChange={(value) => setDraft('document', value)}
                        onSubmit={() => submitComment('document')}
                        saving={writing === 'document'}
                        busy={!!writing && writing !== 'document'}
                        label="Comment on this file"
                        placeholder="Comment on this file"
                        dataAttr="task-artifact-comment-document"
                    />
                </div>
                <ArtifactCommentThreadList logicProps={logicProps} />
            </PopoverContent>
        </Popover>
    )
}
