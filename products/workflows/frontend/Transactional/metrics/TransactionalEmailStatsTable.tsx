import { Tooltip } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import type { TransactionalEmailStatsRowApi } from 'products/messaging/frontend/generated/api.schemas'

type Rate = 'delivered' | 'bounced' | 'complained' | 'opened' | 'clicked'

// Bounces divide by what was sent, the rest by what arrived, since only a delivered email can be opened or reported.
const RATE_BASE: Record<Rate, 'sent' | 'delivered'> = {
    delivered: 'sent',
    bounced: 'sent',
    complained: 'delivered',
    opened: 'delivered',
    clicked: 'delivered',
}

const RATE_TITLE: Record<Rate, string> = {
    delivered: 'Delivered',
    bounced: 'Bounced',
    complained: 'Marked as spam',
    opened: 'Opened',
    clicked: 'Clicked',
}

function RateCell({ row, rate }: { row: TransactionalEmailStatsRowApi; rate: Rate }): JSX.Element {
    const base = row[RATE_BASE[rate]]
    const count = row[rate]
    if (base === 0) {
        return <span className="text-secondary">–</span>
    }
    return (
        <Tooltip title={`${humanFriendlyNumber(count)} of ${humanFriendlyNumber(base)} ${RATE_BASE[rate]}`}>
            <span className="tabular-nums">{percentage(count / base, 1, true)}</span>
        </Tooltip>
    )
}

const PAGE_SIZE = 20

export interface TransactionalEmailStatsTableProps {
    // Keeps the page and sort order in the URL separate for each table on the tab.
    id: string
    rows: TransactionalEmailStatsRowApi[] | null
    loading: boolean
    groupTitle: string
    // Where the group's name links to, when it has a page.
    linkFor?: (row: TransactionalEmailStatsRowApi) => string | null
    emptyState: string
    dataAttr: string
}

export function TransactionalEmailStatsTable({
    id,
    rows,
    loading,
    groupTitle,
    linkFor,
    emptyState,
    dataAttr,
}: TransactionalEmailStatsTableProps): JSX.Element {
    return (
        <LemonTable<TransactionalEmailStatsRowApi>
            id={id}
            dataSource={rows ?? []}
            loading={loading}
            rowKey="key"
            data-attr={dataAttr}
            columns={[
                {
                    title: groupTitle,
                    key: 'label',
                    render: (_, row) => {
                        const name = row.label || <span className="text-secondary">Deleted email</span>
                        const to = linkFor?.(row)
                        return to ? <LemonTableLink to={to} title={name} /> : name
                    },
                },
                {
                    title: 'Sent',
                    key: 'sent',
                    align: 'right',
                    sorter: (a, b) => a.sent - b.sent,
                    render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.sent)}</span>,
                },
                ...(['delivered', 'bounced', 'complained', 'opened', 'clicked'] as const).map((rate) => ({
                    title: RATE_TITLE[rate],
                    key: rate,
                    align: 'right' as const,
                    render: (_: unknown, row: TransactionalEmailStatsRowApi) => <RateCell row={row} rate={rate} />,
                })),
                {
                    title: 'Failed',
                    key: 'failed',
                    align: 'right',
                    render: (_, row) => (
                        <span className={row.failed > 0 ? 'tabular-nums text-danger' : 'tabular-nums text-secondary'}>
                            {humanFriendlyNumber(row.failed)}
                        </span>
                    ),
                },
            ]}
            defaultSorting={{ columnKey: 'sent', order: -1 }}
            pagination={{ pageSize: PAGE_SIZE, hideOnSinglePage: true }}
            emptyState={emptyState}
        />
    )
}
