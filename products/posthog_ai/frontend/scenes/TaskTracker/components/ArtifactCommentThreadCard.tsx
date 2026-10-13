import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconPin } from '@posthog/icons'
import { Badge, Button, Text, cn } from '@posthog/quill-primitives'

import { ArtifactCommentThread, threadAnchorLabel } from '../artifactComments'
import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { taskRunArtifactsLogic } from '../taskRunArtifactsLogic'
import { ArtifactCommentComposer } from './ArtifactCommentComposer'
import { ArtifactCommentThreadEntries } from './ArtifactCommentThreadEntries'

/** One comment thread in the comments menu: what it is about, its comments, and a reply box. */
export function ArtifactCommentThreadCard({
    logicProps,
    thread,
}: {
    logicProps: TaskArtifactCommentsLogicProps
    thread: ArtifactCommentThread
}): JSX.Element {
    const { activeThreadId, writing, drafts } = useValues(taskArtifactCommentsLogic(logicProps))
    const { activateThread, replyToThread, setDraft } = useActions(taskArtifactCommentsLogic(logicProps))
    const { todayPhone } = useValues(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    const ref = useRef<HTMLElement>(null)
    const rootId = thread.root.id
    const active = activeThreadId === rootId
    const { anchor } = thread

    // A click on a highlight or a pin in the preview brings its thread into view.
    useEffect(() => {
        if (active) {
            ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        }
    }, [active])

    return (
        <section
            ref={ref}
            aria-label={threadAnchorLabel(thread)}
            data-selected={active || undefined}
            className={cn('flex flex-col gap-1 rounded-md py-2', active && 'bg-fill-selected')}
            data-attr="task-artifact-comment-thread"
        >
            {(anchor?.kind === 'text' || thread.pinNumber || thread.resolved) && (
                <div className="flex min-w-0 flex-wrap items-center gap-1 px-2">
                    {anchor?.kind === 'text' && (
                        <button
                            type="button"
                            className="w-full min-w-0 cursor-pointer border-l-2 border-warning py-0.5 pl-2 text-left"
                            onClick={() => activateThread(active ? null : rootId)}
                            aria-pressed={active}
                            data-attr="task-artifact-comment-thread-quote"
                        >
                            <Text size="xs" variant="muted" render={<span />} className="line-clamp-2 italic">
                                {anchor.quote}
                            </Text>
                        </button>
                    )}
                    {thread.pinNumber && (
                        <button
                            type="button"
                            className="cursor-pointer rounded-sm"
                            onClick={() => activateThread(active ? null : rootId)}
                            aria-pressed={active}
                            data-attr="task-artifact-comment-thread-pin"
                        >
                            <Badge variant="info">
                                <IconPin />
                                {`Pin ${thread.pinNumber}`}
                            </Badge>
                        </button>
                    )}
                    {thread.resolved && <Badge variant="completed">Resolved</Badge>}
                </div>
            )}
            <ArtifactCommentThreadEntries logicProps={logicProps} thread={thread} />
            {/* Like Desktop, the reply box opens on the picked thread, so a long list stays short. */}
            {/* pl-9 lines the reply controls up with the comment text, past the avatar gutter. */}
            {!thread.resolved && !active && !drafts[rootId] && (
                <div className="pr-2 pl-9">
                    <Button
                        size="xs"
                        variant="outline"
                        onClick={() => activateThread(rootId)}
                        data-attr="task-artifact-comment-reply-open"
                    >
                        Reply
                    </Button>
                </div>
            )}
            {!thread.resolved && (active || !!drafts[rootId]) && (
                <div className="pr-2 pl-9">
                    <ArtifactCommentComposer
                        value={drafts[rootId] ?? ''}
                        onChange={(value) => setDraft(rootId, value)}
                        onSubmit={() => replyToThread(rootId)}
                        saving={writing === rootId}
                        busy={!!writing && writing !== rootId}
                        label="Reply"
                        placeholder="Reply"
                        submitLabel="Reply"
                        rows={1}
                        showShortcut={!todayPhone}
                        dataAttr="task-artifact-comment-reply"
                    />
                </div>
            )}
        </section>
    )
}
