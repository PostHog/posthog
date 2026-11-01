import { LemonTable } from '@posthog/lemon-ui'

import { FailedPushTokenRow } from './pushTokenImport'

const TOKEN_TAIL_LENGTH = 6

/** Lists the lines of an import that were not stored, with the reason for each. */
export function PushTokenFailedRowsTable({ rows }: { rows: FailedPushTokenRow[] }): JSX.Element {
    return (
        <LemonTable
            size="small"
            dataSource={rows}
            rowKey={(row) => `${row.line}-${row.distinct_id}-${row.device_token}`}
            pagination={{ pageSize: 10 }}
            data-attr="push-token-import-failed-rows"
            columns={[
                { title: 'Line', dataIndex: 'line', width: 0 },
                {
                    title: 'Distinct ID',
                    dataIndex: 'distinct_id',
                    render: (_, row) => <span className="break-all">{row.distinct_id || '-'}</span>,
                },
                {
                    title: 'Token ends with',
                    dataIndex: 'device_token',
                    render: (_, row) => (
                        <span className="font-mono text-xs">
                            {row.device_token ? `…${row.device_token.slice(-TOKEN_TAIL_LENGTH)}` : '-'}
                        </span>
                    ),
                },
                { title: 'Reason', dataIndex: 'reason' },
            ]}
        />
    )
}
