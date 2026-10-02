import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconComment, IconWarning, IconX } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Label,
    Separator,
    Skeleton,
    SkeletonText,
    Switch,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill-primitives'

import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { taskRunArtifactsLogic } from '../taskRunArtifactsLogic'
import { ArtifactCommentComposer } from './ArtifactCommentComposer'
import { ArtifactCommentThreadCard } from './ArtifactCommentThreadCard'

const EMPTY_HINT = 'Comment on the whole file above.'

function ThreadList({ logicProps }: { logicProps: TaskArtifactCommentsLogicProps }): JSX.Element {
    const { visibleThreads, threads, commentsLoadFailed, commentsLoading } = useValues(
        taskArtifactCommentsLogic(logicProps)
    )
    const { loadComments } = useActions(taskArtifactCommentsLogic(logicProps))
    if (!threads) {
        if (commentsLoadFailed) {
            return (
                <Empty className="min-h-0 flex-1 border-0">
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
            <Empty className="min-h-0 flex-1 border-0">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconComment />
                    </EmptyMedia>
                    <EmptyTitle>{threads.length > 0 ? 'No open comments' : 'No comments yet'}</EmptyTitle>
                    <EmptyDescription>{EMPTY_HINT}</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-1">
            {visibleThreads.map((thread, index) => (
                <Fragment key={thread.root.id}>
                    {index > 0 && <Separator />}
                    <ArtifactCommentThreadCard logicProps={logicProps} thread={thread} />
                </Fragment>
            ))}
        </div>
    )
}

/** The comment threads on the open artifact version, with a box to comment on the whole file. */
export function ArtifactCommentsPanel({ logicProps }: { logicProps: TaskArtifactCommentsLogicProps }): JSX.Element {
    const { resolvedCount, showResolved, drafts, writing } = useValues(taskArtifactCommentsLogic(logicProps))
    const { setShowResolved, setDraft, submitComment } = useActions(taskArtifactCommentsLogic(logicProps))
    const { setCommentsOpen } = useActions(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    const switchId = `task-artifact-comments-show-resolved-${logicProps.artifactId}`
    return (
        <aside
            aria-label="Comments"
            // Below this width the panel covers the preview, so the preview keeps a readable width.
            className="absolute inset-y-0 right-0 z-20 flex w-full max-w-80 flex-col border-l border-border bg-background shadow-md @[64rem]/main-content:static @[64rem]/main-content:w-80 @[64rem]/main-content:shrink-0 @[64rem]/main-content:shadow-none"
            data-attr="task-artifact-comments-panel"
        >
            <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3">
                <Text size="xs" weight="medium" variant="muted" render={<span />}>
                    Comments
                </Text>
                <div className="ml-auto flex items-center gap-2">
                    {resolvedCount > 0 && (
                        <>
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
                        </>
                    )}
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <Button
                                    size="icon-sm"
                                    aria-label="Close comments"
                                    onClick={() => setCommentsOpen(false)}
                                    data-attr="task-artifact-comments-close"
                                />
                            }
                        >
                            <IconX />
                        </TooltipTrigger>
                        <TooltipContent>Close comments</TooltipContent>
                    </Tooltip>
                </div>
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
            <ThreadList logicProps={logicProps} />
        </aside>
    )
}
