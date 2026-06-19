import { LemonTable } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

interface AttributeRow {
    key: string
    value: string
}

export interface SpanAttributesProps {
    attributes: Record<string, string>
    title: string
    emptyLabel?: string
}

// Key-value list rendering for span attributes, mirroring the Logs attribute KVP list
// (products/logs/.../LogsViewer/LogAttributes). Kept presentational for now — the filter,
// breakdown, and add-as-column actions from the logs version depend on logs-only infra.
export function SpanAttributes({ attributes, title, emptyLabel = 'No attributes' }: SpanAttributesProps): JSX.Element {
    const rows: AttributeRow[] = Object.entries(attributes).map(([key, value]) => ({ key, value }))

    const columns: LemonTableColumns<AttributeRow> = [
        {
            title: 'Key',
            key: 'key',
            dataIndex: 'key',
            width: 0,
            render: (_, record): JSX.Element => (
                <span className="font-mono text-xs text-muted whitespace-nowrap">{record.key}</span>
            ),
        },
        {
            title: 'Value',
            key: 'value',
            dataIndex: 'value',
            render: (_, record): JSX.Element => {
                if (record.value === '') {
                    return <span className="font-mono text-xs text-muted italic">(empty)</span>
                }
                return (
                    <CopyToClipboardInline
                        explicitValue={record.value}
                        description="attribute value"
                        iconSize="xsmall"
                        iconPosition="start"
                        selectable
                        className="gap-1 font-mono text-xs"
                    >
                        {record.value}
                    </CopyToClipboardInline>
                )
            },
        },
    ]

    return (
        <div className="bg-primary overflow-hidden rounded border border-border">
            <div className="px-3 py-2 bg-bg-light border-b border-border">
                <span className="text-xs font-semibold text-muted uppercase">{title}</span>
            </div>
            {rows.length === 0 ? (
                <div className="px-3 py-2 text-xs text-muted italic">{emptyLabel}</div>
            ) : (
                <LemonTable embedded showHeader={false} size="small" rowKey="key" columns={columns} dataSource={rows} />
            )}
        </div>
    )
}
