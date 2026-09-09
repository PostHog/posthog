import { useActions, useValues } from 'kea'

import { IconEye } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { ReplayCommentRow, replayCommentsLogic } from './replayCommentsLogic'

const columns: LemonTableColumns<ReplayCommentRow> = [
    {
        title: 'Comment',
        key: 'text',
        render: function Render(_, row) {
            return (
                <div className="flex flex-col gap-1 py-1">
                    <div className="ph-no-capture whitespace-pre-wrap break-words">{row.text}</div>
                    {row.isTask ? (
                        <div>
                            <LemonTag size="small" type={row.isCompleted ? 'success' : 'warning'}>
                                {row.isCompleted ? 'Completed' : 'Task'}
                            </LemonTag>
                        </div>
                    ) : null}
                </div>
            )
        },
    },
    {
        title: 'Recording',
        key: 'recording',
        width: 0,
        render: function Render(_, row) {
            if (!row.recordingUrl) {
                return null
            }
            return (
                <Link
                    to={row.recordingUrl}
                    buttonProps={{ size: 'sm', icon: <IconEye /> }}
                    data-attr="replay-comments-view-recording"
                >
                    {row.timeInRecording ?? 'Watch'}
                </Link>
            )
        },
    },
    {
        title: 'Commented',
        key: 'createdAt',
        width: 0,
        render: function Render(_, row) {
            return <TZLabel time={row.createdAt} />
        },
    },
]

export function ReplayComments(): JSX.Element {
    const { commentRows, firstPageLoading, commentPageLoading, hasMoreComments, hasLoadError } =
        useValues(replayCommentsLogic)
    const { loadReplayComments, loadMoreReplayComments } = useActions(replayCommentsLogic)

    if (hasLoadError) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: loadReplayComments,
                    'data-attr': 'replay-comments-retry',
                }}
            >
                Could not load your comments. Try again, and contact support if it keeps happening.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonTable
                columns={columns}
                dataSource={commentRows}
                loading={firstPageLoading}
                rowKey="id"
                nouns={['comment', 'comments']}
                emptyState="You have not commented on a recording yet. Open a recording and add a comment to see it here."
            />
            {hasMoreComments ? (
                <div className="flex justify-center">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={loadMoreReplayComments}
                        loading={commentPageLoading}
                        data-attr="replay-comments-load-more"
                    >
                        Load more
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
