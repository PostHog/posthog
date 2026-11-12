import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSkeleton, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { NOT_SENT_ROW_LIMIT, NotSentKind, notSentTotal } from './broadcastNotSent'
import { broadcastSentLogic } from './broadcastSentLogic'

const KIND_TAG: Record<NotSentKind, { label: string; type: LemonTagType }> = {
    failed: { label: 'Failed', type: 'danger' },
    skipped: { label: 'Skipped', type: 'warning' },
    canceled: { label: 'Canceled', type: 'muted' },
}

/** People in a run who got no message, with the reason. Reads the bound broadcastSentLogic. */
export function BroadcastRunNotSent({ runFinished }: { runFinished: boolean }): JSX.Element | null {
    const { notSent, notSentLoading, notSentFailed } = useValues(broadcastSentLogic)
    const { watchNotSent, loadNotSent } = useActions(broadcastSentLogic)

    useEffect(() => {
        watchNotSent(runFinished)
    }, [watchNotSent, runFinished])

    if (notSentLoading && notSent === null) {
        return <LemonSkeleton className="h-8" />
    }
    if (notSentFailed && notSent === null) {
        return (
            <span className="flex flex-wrap items-center gap-2 text-muted">
                Couldn't load who this run didn't send to.
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={loadNotSent}
                    loading={notSentLoading}
                    data-attr="broadcast-run-not-sent-retry"
                >
                    Try again
                </LemonButton>
            </span>
        )
    }
    const total = notSent ? notSentTotal(notSent.counts) : 0
    if (!notSent || total === 0) {
        return null
    }

    const breakdown = (Object.keys(KIND_TAG) as NotSentKind[])
        .filter((kind) => notSent.counts[kind] > 0)
        .map((kind) => `${humanFriendlyNumber(notSent.counts[kind])} ${KIND_TAG[kind].label.toLowerCase()}`)
        .join(', ')

    return (
        <div className="flex flex-col gap-2" data-attr="broadcast-run-not-sent">
            <div className="flex flex-wrap items-baseline gap-x-2">
                <h3 className="m-0 text-sm font-semibold">{`Not sent (${humanFriendlyNumber(total)})`}</h3>
                <span className="text-xs text-muted">{breakdown}</span>
                {total > notSent.rows.length ? (
                    <span className="text-xs text-muted">{`Showing the latest ${NOT_SENT_ROW_LIMIT}`}</span>
                ) : null}
            </div>
            <LemonTable
                size="small"
                dataSource={notSent.rows}
                rowKey="invocationId"
                columns={[
                    {
                        title: 'Person',
                        key: 'person',
                        render: (_, row) =>
                            row.personId ? (
                                <Link to={urls.personByUUID(row.personId)} className="whitespace-nowrap">
                                    {row.distinctId || row.personId}
                                </Link>
                            ) : (
                                <span className="whitespace-nowrap">{row.distinctId}</span>
                            ),
                    },
                    {
                        title: 'Status',
                        key: 'kind',
                        render: (_, row) => (
                            <LemonTag type={KIND_TAG[row.kind].type}>{KIND_TAG[row.kind].label}</LemonTag>
                        ),
                    },
                    {
                        title: 'Reason',
                        key: 'reason',
                        render: (_, row) => (
                            <span className="wrap-anywhere">{row.reason || <span className="text-muted">-</span>}</span>
                        ),
                    },
                ]}
            />
        </div>
    )
}
