import { useActions, useValues } from 'kea'
import { KeyboardEvent, useState } from 'react'

import { IconEllipsis, IconExternal, IconGithub, IconPencil, IconEmojiAdd, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTextArea, Link, Popover, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import type { PullRequestCommentReactionApi } from 'products/signals/frontend/generated/api.schemas'

import {
    ClientPullRequestComment,
    DraftThread,
    inboxReportDetailLogic,
    InboxReportDetailLogicProps,
    ReviewThread,
    threadKey,
} from '../../logics/inboxReportDetailLogic'

// The card is dropped into @pierre/diffs' annotation slot, which spans the full row width under the
// diff line (gutter included). Indent past the gutter and cap the width so a thread reads like a
// focused conversation, not a full-bleed banner. Border color is per-variant so it never conflicts.
const CARD_BASE =
    'pointer-events-auto my-1.5 ml-2 mr-3 max-w-[52rem] overflow-hidden rounded-lg border bg-surface-primary font-sans shadow-sm'

// The reactions GitHub supports, in the order its own picker shows them, with the emoji we render.
const REACTIONS: { content: string; emoji: string; label: string }[] = [
    { content: '+1', emoji: '👍', label: 'thumbs up' },
    { content: '-1', emoji: '👎', label: 'thumbs down' },
    { content: 'laugh', emoji: '😄', label: 'laugh' },
    { content: 'hooray', emoji: '🎉', label: 'hooray' },
    { content: 'confused', emoji: '😕', label: 'confused' },
    { content: 'heart', emoji: '❤️', label: 'heart' },
    { content: 'rocket', emoji: '🚀', label: 'rocket' },
    { content: 'eyes', emoji: '👀', label: 'eyes' },
]
/** GitHub-style add-reaction picker: a compact 3-column emoji grid in a popover — emoji only, no labels. */
function ReactionPicker({ onPick }: { onPick: (content: string) => void }): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="bottom-start"
            overlay={
                <div className="grid grid-cols-3 gap-0.5 p-1">
                    {REACTIONS.map((r) => (
                        <button
                            key={r.content}
                            type="button"
                            title={r.label}
                            aria-label={`React ${r.label}`}
                            onClick={() => {
                                onPick(r.content)
                                setOpen(false)
                            }}
                            className="flex size-8 items-center justify-center rounded text-base transition-colors hover:bg-fill-highlight-50"
                        >
                            {r.emoji}
                        </button>
                    ))}
                </div>
            }
        >
            <LemonButton
                size="xsmall"
                icon={<IconEmojiAdd />}
                tooltip="Add reaction"
                active={open}
                onClick={() => setOpen((o) => !o)}
            />
        </Popover>
    )
}

/** Reaction pills (grouped by emoji, the viewer's own highlighted) plus an add-reaction picker. */
function ReactionBar({
    logicProps,
    comment,
}: {
    logicProps: InboxReportDetailLogicProps
    comment: ClientPullRequestComment
}): JSX.Element | null {
    const { currentUserGithubLogin, hasPersonalGithub } = useValues(inboxReportDetailLogic(logicProps))
    const { toggleReviewCommentReaction } = useActions(inboxReportDetailLogic(logicProps))
    const reactions = comment.reactions ?? []
    const pending = !!comment.pending

    // Group by content → count + whether the viewer reacted, preserving GitHub's canonical order.
    const groups = REACTIONS.map(({ content, emoji, label }) => {
        const forContent = reactions.filter((r: PullRequestCommentReactionApi) => r.content === content)
        return {
            content,
            emoji,
            label,
            count: forContent.length,
            mine: forContent.some((r) => r.user_login === currentUserGithubLogin),
        }
    }).filter((g) => g.count > 0)

    if (groups.length === 0 && (!hasPersonalGithub || pending)) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-1">
            {groups.map((g) => (
                <Tooltip key={g.content} title={g.mine ? `You reacted ${g.label}` : g.label}>
                    <button
                        type="button"
                        disabled={!hasPersonalGithub || pending}
                        onClick={() => toggleReviewCommentReaction(comment.id, g.content)}
                        className={`flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-xs tabular-nums transition-colors disabled:opacity-60 ${
                            g.mine
                                ? 'border-accent bg-accent-highlight text-accent-primary'
                                : 'border-primary bg-surface-secondary text-secondary hover:border-secondary'
                        }`}
                    >
                        <span className="text-[0.8125rem] leading-none">{g.emoji}</span>
                        {g.count}
                    </button>
                </Tooltip>
            ))}
            {hasPersonalGithub && !pending && (
                <ReactionPicker onPick={(content) => toggleReviewCommentReaction(comment.id, content)} />
            )}
        </div>
    )
}

/** One comment inside a thread: avatar, author, time, actions (own comments), markdown body, reactions. */
function ThreadComment({
    logicProps,
    comment,
}: {
    logicProps: InboxReportDetailLogicProps
    comment: ClientPullRequestComment
}): JSX.Element {
    const { currentUserGithubLogin, editingCommentId } = useValues(inboxReportDetailLogic(logicProps))
    const { setEditingCommentId, editReviewComment, deleteReviewComment } = useActions(
        inboxReportDetailLogic(logicProps)
    )
    const isMine = !!comment.author && comment.author === currentUserGithubLogin
    const editing = editingCommentId === comment.id
    const sending = comment.pending === 'sending'
    const failed = comment.pending === 'failed'

    return (
        <div className={`flex gap-2.5 px-3 py-2.5 ${sending ? 'opacity-60' : ''}`}>
            {comment.author_avatar_url ? (
                <img
                    src={comment.author_avatar_url}
                    alt={comment.author ?? 'author'}
                    className="mt-0.5 size-5 shrink-0 rounded-full bg-fill-highlight-50"
                    loading="lazy"
                />
            ) : (
                <span className="mt-0.5 size-5 shrink-0 rounded-full bg-fill-highlight-100" aria-hidden />
            )}
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex min-w-0 items-center gap-x-2 text-xs text-tertiary">
                    <span className="font-semibold text-secondary">{comment.author ?? 'Unknown'}</span>
                    {comment.created_at && !comment.pending && <TZLabel time={comment.created_at} />}
                    {sending && <span className="italic">Posting…</span>}
                    {failed && <span className="text-danger">Failed to post</span>}
                    <div className="ml-auto flex items-center gap-0.5">
                        {comment.url && (
                            <Link
                                to={comment.url}
                                target="_blank"
                                className="inline-flex items-center p-1 text-tertiary"
                                aria-label="Open on GitHub"
                            >
                                <IconExternal className="size-3.5" />
                            </Link>
                        )}
                        {isMine && !comment.pending && !editing && (
                            <LemonMenu
                                items={[
                                    {
                                        label: 'Edit',
                                        icon: <IconPencil />,
                                        onClick: () => setEditingCommentId(comment.id),
                                    },
                                    {
                                        label: 'Delete',
                                        icon: <IconTrash />,
                                        status: 'danger',
                                        onClick: () => deleteReviewComment(comment.id),
                                    },
                                ]}
                                placement="bottom-end"
                            >
                                <LemonButton size="xsmall" icon={<IconEllipsis />} tooltip="Comment actions" />
                            </LemonMenu>
                        )}
                    </div>
                </div>
                {editing ? (
                    <CommentEditor
                        initialBody={comment.body}
                        onCancel={() => setEditingCommentId(null)}
                        onSave={(body) => editReviewComment(comment.id, body)}
                    />
                ) : comment.body ? (
                    <LemonMarkdown className="text-[0.8125rem] leading-relaxed text-primary break-words" disableImages>
                        {comment.body}
                    </LemonMarkdown>
                ) : (
                    <span className="text-xs italic text-tertiary">No description</span>
                )}
                {!editing && <ReactionBar logicProps={logicProps} comment={comment} />}
            </div>
        </div>
    )
}

/** Inline editor for an existing comment: pre-filled textarea, ⌘⏎ to save, Escape to cancel. */
function CommentEditor({
    initialBody,
    onCancel,
    onSave,
}: {
    initialBody: string
    onCancel: () => void
    onSave: (body: string) => void
}): JSX.Element {
    const [body, setBody] = useState(initialBody)
    const dirty = body.trim().length > 0 && body !== initialBody
    const save = (): void => {
        if (dirty) {
            onSave(body.trim())
        }
    }
    return (
        <div className="flex flex-col gap-1.5">
            <LemonTextArea
                autoFocus
                value={body}
                onChange={setBody}
                onPressCmdEnter={save}
                onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => {
                    if (e.key === 'Escape') {
                        e.preventDefault()
                        onCancel()
                    }
                }}
                minRows={2}
                maxRows={12}
                className="text-[0.8125rem]"
            />
            <div className="flex items-center justify-end gap-1.5">
                <LemonButton type="tertiary" size="xsmall" onClick={onCancel}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="xsmall"
                    onClick={save}
                    disabledReason={!dirty ? 'Make a change first' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}

/** Borderless composer (the card is the frame): collapsed "Reply…" state, ⌘⏎ submit, in-flight guard. */
function ThreadComposer({
    logicProps,
    composerKey,
    placeholder,
    startExpanded,
    onCancel,
    onSubmit,
}: {
    logicProps: InboxReportDetailLogicProps
    composerKey: string
    placeholder: string
    /** Draft threads open straight into the textarea; existing threads start at the collapsed "Reply…" pill. */
    startExpanded: boolean
    onCancel?: () => void
    onSubmit: (body: string) => void
}): JSX.Element {
    const { postingThreadKey, hasPersonalGithub } = useValues(inboxReportDetailLogic(logicProps))
    const [expanded, setExpanded] = useState(startExpanded)
    const [body, setBody] = useState('')
    const posting = postingThreadKey === composerKey
    const anyPosting = postingThreadKey !== null

    if (!hasPersonalGithub) {
        return (
            <div className="flex items-center justify-between gap-2 bg-surface-secondary px-3 py-2">
                <span className="text-xs text-tertiary">Comments post to GitHub as you</span>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconGithub />}
                    to={urls.settings('user-personal-integrations')}
                    targetBlank
                >
                    Connect GitHub
                </LemonButton>
            </div>
        )
    }

    if (!expanded) {
        return (
            <div className="p-2">
                <button
                    type="button"
                    onClick={() => setExpanded(true)}
                    className="w-full cursor-text rounded-md border border-primary bg-bg-light px-3 py-1.5 text-left text-xs text-tertiary transition-colors hover:border-secondary"
                >
                    Reply…
                </button>
            </div>
        )
    }

    const canSubmit = body.trim().length > 0 && !anyPosting
    const submit = (): void => {
        if (canSubmit) {
            onSubmit(body.trim())
            setBody('')
        }
    }
    const cancel = (): void => (onCancel ? onCancel() : setExpanded(false))
    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>): void => {
        if (e.key === 'Escape') {
            e.preventDefault()
            cancel()
        }
    }

    return (
        // One column: `pl-3` defines the left inset; the textarea's own horizontal padding is zeroed
        // so its text and the footer below it start on the same line. `pr-2` pulls the footer's
        // Cancel/Comment buttons in so they align neatly with the card's right edge.
        <div className="flex flex-col gap-1.5 pl-3 pr-2 py-2">
            <LemonTextArea
                autoFocus
                hideFocus
                value={body}
                onChange={setBody}
                onPressCmdEnter={submit}
                onKeyDown={handleKeyDown}
                placeholder={placeholder}
                minRows={2}
                maxRows={12}
                disabled={posting}
                className="!bg-transparent !px-0 text-[0.8125rem]"
                data-attr="inline-review-comment-textarea"
            />
            <div className="flex items-center justify-between gap-2">
                <span className="text-[0.6875rem] text-tertiary">Markdown · ⌘⏎ to comment</span>
                <div className="flex items-center gap-1.5">
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        onClick={cancel}
                        disabledReason={posting ? 'Posting…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        onClick={submit}
                        loading={posting}
                        disabledReason={
                            body.trim().length === 0
                                ? 'Write a comment first'
                                : anyPosting && !posting
                                  ? 'Another comment is posting'
                                  : undefined
                        }
                        data-attr="inline-review-comment-submit"
                    >
                        Comment
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

/** An existing review thread rendered inline under its diff line: comments + reply composer. */
export function InlineReviewThread({
    logicProps,
    thread,
}: {
    logicProps: InboxReportDetailLogicProps
    thread: ReviewThread
}): JSX.Element {
    const { postReviewComment } = useActions(inboxReportDetailLogic(logicProps))
    const key = threadKey(thread)

    return (
        <div className={`${CARD_BASE} border-primary`}>
            <div className="flex flex-col divide-y divide-primary">
                {thread.comments.map((comment) => (
                    <ThreadComment key={comment.id} logicProps={logicProps} comment={comment} />
                ))}
            </div>
            <div className="border-t border-primary bg-surface-secondary">
                <ThreadComposer
                    logicProps={logicProps}
                    composerKey={key}
                    placeholder="Reply to this thread"
                    startExpanded={false}
                    onSubmit={(body) => postReviewComment({ body, inReplyTo: thread.rootId, key })}
                />
            </div>
        </div>
    )
}

/** A fresh, not-yet-posted thread on a diff line: just the composer, accent-framed and focused. */
export function InlineDraftThread({
    logicProps,
    draft,
}: {
    logicProps: InboxReportDetailLogicProps
    draft: DraftThread
}): JSX.Element {
    const { postReviewComment, closeDraftThread } = useActions(inboxReportDetailLogic(logicProps))
    const key = threadKey(draft)

    return (
        <div className={`${CARD_BASE} border-accent`}>
            <ThreadComposer
                logicProps={logicProps}
                composerKey={key}
                placeholder="Leave a comment"
                startExpanded
                onCancel={closeDraftThread}
                onSubmit={(body) =>
                    postReviewComment({ body, path: draft.path, line: draft.line, side: draft.side, key })
                }
            />
        </div>
    )
}
