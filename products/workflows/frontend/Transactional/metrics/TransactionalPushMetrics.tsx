import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import type { TransactionalPushStatsRowApi } from 'products/messaging/frontend/generated/api.schemas'

import { transactionalPushMetricsLogic } from './transactionalPushMetricsLogic'

function Count({ value }: { value: number }): JSX.Element {
    return <span className="tabular-nums">{humanFriendlyNumber(value)}</span>
}

export function TransactionalPushMetrics(): JSX.Element {
    const { pushStats, pushStatsLoading, pushStatsFailed } = useValues(transactionalPushMetricsLogic)
    const { loadPushStats } = useActions(transactionalPushMetricsLogic)

    const totals = (pushStats ?? []).reduce(
        (sum, row) => ({
            sent: sum.sent + row.sent,
            not_sent: sum.not_sent + row.not_sent,
            failed: sum.failed + row.failed,
        }),
        { sent: 0, not_sent: 0, failed: 0 }
    )

    return (
        <SceneSection
            title="Push notifications"
            description="Sent reached at least one of the person's devices. Not sent reached none, for example because the person has no device registered."
        >
            {pushStatsFailed && !pushStatsLoading && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadPushStats(),
                        'data-attr': 'transactional-push-metrics-retry',
                    }}
                >
                    The push numbers couldn't load. Check your connection and try again.
                </LemonBanner>
            )}
            <LemonTable<TransactionalPushStatsRowApi>
                dataSource={pushStats ?? []}
                loading={pushStatsLoading}
                rowKey="template_id"
                data-attr="transactional-push-metrics-by-push"
                columns={[
                    {
                        title: 'Push notification',
                        key: 'template',
                        render: (_, row) => (
                            <LemonTableLink
                                to={urls.transactionalPush(row.template_id)}
                                title={row.template_name || 'Unnamed push notification'}
                            />
                        ),
                    },
                    { title: 'Sent', key: 'sent', align: 'right', render: (_, row) => <Count value={row.sent} /> },
                    {
                        title: 'Not sent',
                        key: 'not_sent',
                        align: 'right',
                        render: (_, row) => <Count value={row.not_sent} />,
                    },
                    {
                        title: 'Failed',
                        key: 'failed',
                        align: 'right',
                        render: (_, row) => <Count value={row.failed} />,
                    },
                ]}
                footer={
                    pushStats && pushStats.length > 1 ? (
                        <div className="flex justify-end gap-6 px-3 py-2 font-semibold tabular-nums">
                            <span>Sent {humanFriendlyNumber(totals.sent)}</span>
                            <span>Not sent {humanFriendlyNumber(totals.not_sent)}</span>
                            <span>Failed {humanFriendlyNumber(totals.failed)}</span>
                        </div>
                    ) : undefined
                }
                emptyState={
                    pushStatsFailed
                        ? "The push numbers couldn't load"
                        : 'No push notifications were sent in this period'
                }
            />
        </SceneSection>
    )
}
