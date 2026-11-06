import { LemonTable } from '@posthog/lemon-ui'

import type { PushTokenImportRowFailureApi } from 'products/workflows/frontend/generated/api.schemas'
import { PushTokenImportRowFailureReasonEnumApi } from 'products/workflows/frontend/generated/api.schemas'

// The server's detail for these is written for API callers, so the table names the reason in the dialog's words.
const REASON_LABELS: Partial<Record<PushTokenImportRowFailureApi['reason'], string>> = {
    [PushTokenImportRowFailureReasonEnumApi.UnknownPerson]: 'No person has this distinct ID',
    [PushTokenImportRowFailureReasonEnumApi.NotStored]: 'Not stored, import it again',
    [PushTokenImportRowFailureReasonEnumApi.PersonProcessingDisabled]: 'Person processing is off for this person',
}

/** Lists the lines of an import that were not stored, with the reason for each. */
export function PushTokenFailedRowsTable({ rows }: { rows: PushTokenImportRowFailureApi[] }): JSX.Element {
    return (
        <LemonTable
            size="small"
            dataSource={rows}
            rowKey={(row) => `${row.line}-${row.reason}`}
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
                    dataIndex: 'device_token_suffix',
                    render: (_, row) => (
                        <span className="font-mono text-xs">
                            {row.device_token_suffix ? `…${row.device_token_suffix}` : '-'}
                        </span>
                    ),
                },
                { title: 'Reason', dataIndex: 'detail', render: (_, row) => REASON_LABELS[row.reason] ?? row.detail },
            ]}
        />
    )
}
