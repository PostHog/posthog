import { ReactNode } from 'react'

import {
    Avatar,
    AvatarFallback,
    ThreadItem,
    ThreadItemActions,
    ThreadItemAuthor,
    ThreadItemBody,
    ThreadItemContent,
    ThreadItemGutter,
    ThreadItemHeader,
    ThreadItemTimestamp,
} from '@posthog/quill-primitives'

import { dayjs } from 'lib/dayjs'
import { fullNameOrEmail } from 'lib/utils/strings'

import type { CommentApi } from 'products/platform_features/frontend/generated/api.schemas'
import { TaskUserAvatar } from 'products/tasks/frontend/spaces/TaskUserAvatar'

/** One comment in a thread: who wrote it, when, and what it says. `actions` show on hover and focus. */
export function ArtifactCommentEntry({ comment, actions }: { comment: CommentApi; actions?: ReactNode }): JSX.Element {
    const name = comment.created_by ? fullNameOrEmail(comment.created_by) : 'Deleted user'
    return (
        <ThreadItem>
            {/* The narrow panel has no continuation timestamps, so the gutter only needs room for the avatar. */}
            <ThreadItemGutter className="w-5">
                {comment.created_by ? (
                    <TaskUserAvatar
                        user={{
                            uuid: comment.created_by.uuid,
                            email: comment.created_by.email,
                            first_name: comment.created_by.first_name ?? '',
                            last_name: comment.created_by.last_name ?? '',
                        }}
                    />
                ) : (
                    <Avatar size="xs">
                        <AvatarFallback>?</AvatarFallback>
                    </Avatar>
                )}
            </ThreadItemGutter>
            <ThreadItemContent>
                <ThreadItemHeader>
                    <ThreadItemAuthor className="truncate">{name}</ThreadItemAuthor>
                    <ThreadItemTimestamp dateTime={comment.created_at} title={dayjs(comment.created_at).format('LLL')}>
                        {dayjs(comment.created_at).fromNow()}
                    </ThreadItemTimestamp>
                </ThreadItemHeader>
                <ThreadItemBody className="break-words whitespace-pre-wrap">{comment.content}</ThreadItemBody>
            </ThreadItemContent>
            {actions && <ThreadItemActions aria-label="Comment actions">{actions}</ThreadItemActions>}
        </ThreadItem>
    )
}
