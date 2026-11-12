import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSkeleton, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { HOG_INVOCATIONS_PAGE_SIZE, type RunStatus } from 'scenes/hog-functions/invocations/hogInvocationsLogic'

import { broadcastSentLogic } from './broadcastSentLogic'

const STATUS_LABEL: Partial<Record<RunStatus, { label: string; type: LemonTagType }>> = {
    running: { label: 'Waiting to send', type: 'warning' },
    failed: { label: 'Failed', type: 'danger' },
    canceled: { label: 'Canceled', type: 'muted' },
}

/** People in a run who did not get the message yet or at all, with the reason. Reads the bound broadcastSentLogic. */
export function BroadcastRunNotSent(): JSX.Element | null {
    const { unsent, unsentLoading, unsentFailed } = useValues(broadcastSentLogic)
    const { loadUnsent } = useActions(broadcastSentLogic)

    useEffect(() => {
        loadUnsent()
    }, [loadUnsent])

    if (unsentLoading && unsent === null) {
        return <LemonSkeleton className="h-8" />
    }
    if (unsentFailed) {
        return (
            <span className="flex flex-wrap items-center gap-2 text-muted">
                Couldn't load who this run hasn't sent to.
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={loadUnsent}
                    loading={unsentLoading}
                    data-attr="broadcast-run-not-sent-retry"
                >
                    Try again
                </LemonButton>
            </span>
        )
    }
    if (!unsent?.length) {
        return null
    }

    return (
        <div className="flex flex-col gap-2" data-attr="broadcast-run-not-sent">
            <h3 className="m-0 text-sm font-semibold">
                {unsent.length >= HOG_INVOCATIONS_PAGE_SIZE
                    ? `Not sent (first ${HOG_INVOCATIONS_PAGE_SIZE})`
                    : `Not sent (${unsent.length})`}
            </h3>
            <LemonTable
                size="small"
                dataSource={unsent}
                rowKey="invocation_id"
                columns={[
                    {
                        title: 'Person',
                        key: 'distinct_id',
                        render: (_, row) => (
                            <span className="font-mono text-xs break-all">{row.distinct_id || row.person_id}</span>
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, row) => {
                            const status = STATUS_LABEL[row.status]
                            return status ? <LemonTag type={status.type}>{status.label}</LemonTag> : row.status
                        },
                    },
                    {
                        title: 'Error',
                        key: 'error_message',
                        render: (_, row) => (
                            <span className="wrap-anywhere">
                                {row.error_message || <span className="text-muted">-</span>}
                            </span>
                        ),
                    },
                ]}
            />
        </div>
    )
}
