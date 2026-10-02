import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconCheck, IconPin, IconRefresh } from '@posthog/icons'
import { Badge, Button, Text, ThreadItemAction, ThreadItemGroup, cn } from '@posthog/quill-primitives'

import { ArtifactCommentThread } from '../artifactComments'
import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { ArtifactCommentComposer } from './ArtifactCommentComposer'
import { ArtifactCommentEntry } from './ArtifactCommentEntry'

/** One comment thread: what it is about, its comments, and a reply box. */
export function ArtifactCommentThreadCard({
    logicProps,
    thread,
}: {
    logicProps: TaskArtifactCommentsLogicProps
    thread: ArtifactCommentThread
}): JSX.Element {
    const { activeThreadId, writing, drafts } = useValues(taskArtifactCommentsLogic(logicProps))
    const { activateThread, setThreadResolved, replyToThread, setDraft } = useActions(
        taskArtifactCommentsLogic(logicProps)
    )
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

    const resolveAction = (
        <ThreadItemAction
            label={thread.resolved ? 'Reopen thread' : 'Resolve thread'}
            variant="default"
            loading={writing === rootId}
            disabled={!!writing && writing !== rootId}
            onClick={() => setThreadResolved(rootId, !thread.resolved)}
            data-attr={thread.resolved ? 'task-artifact-comment-reopen' : 'task-artifact-comment-resolve'}
        >
            {thread.resolved ? <IconRefresh /> : <IconCheck />}
        </ThreadItemAction>
    )
    const anchorLabel =
        anchor?.kind === 'text'
            ? `Comments on "${anchor.quote}"`
            : thread.pinNumber
              ? `Comments on pin ${thread.pinNumber}`
              : 'Comments on this file'

    return (
        <section
            ref={ref}
            aria-label={anchorLabel}
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
            <ThreadItemGroup>
                <ArtifactCommentEntry comment={thread.root} actions={resolveAction} />
                {thread.replies.map((reply) => (
                    <ArtifactCommentEntry key={reply.id} comment={reply} />
                ))}
            </ThreadItemGroup>
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
                        dataAttr="task-artifact-comment-reply"
                    />
                </div>
            )}
        </section>
    )
}
