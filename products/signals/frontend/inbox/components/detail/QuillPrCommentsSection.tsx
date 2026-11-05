import { useValues } from 'kea'

import { IconComment, IconExternal } from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    AvatarImage,
    Badge,
    Button,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { PullRequestCommentApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { QuillDetailSection } from './QuillDetailSection'

/** A single PR comment row: avatar, author, relative time, optional file path, then the markdown body. */
function CommentRow({ comment }: { comment: PullRequestCommentApi }): JSX.Element {
    const author = comment.author ?? 'Unknown'
    return (
        <li className="flex min-w-0 gap-2.5">
            <Avatar size="sm">
                {comment.author_avatar_url && <AvatarImage src={comment.author_avatar_url} alt={author} />}
                <AvatarFallback>{author.charAt(0).toUpperCase()}</AvatarFallback>
            </Avatar>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <Text size="xs" variant="muted" render={<div />} className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-semibold text-foreground">{author}</span>
                    {comment.created_at && <TZLabel time={comment.created_at} />}
                    {comment.comment_type === 'review' && comment.path && (
                        <Tooltip>
                            <TooltipTrigger render={<Badge className="max-w-64 font-mono" />}>
                                <span className="truncate">{comment.path}</span>
                            </TooltipTrigger>
                            <TooltipContent>{comment.path}</TooltipContent>
                        </Tooltip>
                    )}
                    {comment.url && (
                        <Button
                            size="icon-xs"
                            aria-label="Open on GitHub"
                            tooltip="Open on GitHub"
                            render={<LinkPrimitive to={comment.url} target="_blank" />}
                        >
                            <IconExternal />
                        </Button>
                    )}
                </Text>
                {comment.body ? (
                    <LemonMarkdown className="text-xs leading-relaxed break-words" disableImages>
                        {comment.body}
                    </LemonMarkdown>
                ) : (
                    <Text size="xs" variant="muted" className="m-0 italic">
                        No content.
                    </Text>
                )}
            </div>
        </li>
    )
}

/** The quill sibling of `PrCommentsSection`, for the report page behind `today-rail-nav`. */
export function QuillPrCommentsSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { prComments, prCommentsLoading, prCommentsError } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )

    // Never loaded yet: show a skeleton. Loaded-but-empty: nothing to show, so drop the section.
    if (prComments === null) {
        if (!prCommentsLoading && !prCommentsError) {
            return null
        }
    } else if (prComments.length === 0 && !prCommentsError) {
        return null
    }

    return (
        <QuillDetailSection
            icon={<IconComment />}
            title="Comments"
            collapsible
            defaultCollapsed
            meta={
                prComments && prComments.length > 0 ? (
                    <Text size="xxs" variant="muted" render={<span />} className="tabular-nums">
                        {`${prComments.length} comment${prComments.length === 1 ? '' : 's'}`}
                    </Text>
                ) : undefined
            }
        >
            {prCommentsError ? (
                <Text size="xs" variant="destructive" className="m-0 py-2">
                    {prCommentsError}
                </Text>
            ) : prComments === null ? (
                <div className="flex flex-col gap-3">
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-4/5" />
                </div>
            ) : (
                <ul className="m-0 flex list-none flex-col gap-4 p-0">
                    {prComments.map((comment) => (
                        <CommentRow key={comment.id} comment={comment} />
                    ))}
                </ul>
            )}
        </QuillDetailSection>
    )
}
