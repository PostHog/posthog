import { LemonTable } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

export interface MetricSampleAttributesProps {
    title: string
    attributes: Record<string, string>
}

export function MetricSampleAttributes({ title, attributes }: MetricSampleAttributesProps): JSX.Element | null {
    const rows = Object.entries(attributes).map(([key, value]) => ({ key, value }))
    if (rows.length === 0) {
        return null
    }

    return (
        <div className="bg-primary overflow-hidden rounded border border-border">
            <div className="px-3 py-2 bg-bg-light border-b border-border">
                <span className="text-xs font-semibold text-muted uppercase">{title}</span>
            </div>
            <LemonTable
                embedded
                showHeader={false}
                size="small"
                rowKey="key"
                columns={[
                    {
                        title: 'Key',
                        key: 'key',
                        dataIndex: 'key',
                        width: 0,
                        render: (_, record) => (
                            <span className="font-mono text-xs text-muted whitespace-nowrap">{record.key}</span>
                        ),
                    },
                    {
                        title: 'Value',
                        key: 'value',
                        dataIndex: 'value',
                        render: (_, record) =>
                            record.value === '' ? (
                                <span className="font-mono text-xs text-muted italic">(empty)</span>
                            ) : (
                                <CopyToClipboardInline
                                    explicitValue={record.value}
                                    description="attribute value"
                                    iconSize="xsmall"
                                    iconPosition="start"
                                    selectable
                                    className="gap-1 font-mono text-xs"
                                >
                                    <span>{record.value}</span>
                                </CopyToClipboardInline>
                            ),
                    },
                ]}
                dataSource={rows}
            />
        </div>
    )
}
