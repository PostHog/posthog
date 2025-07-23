import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { TZLabel } from 'lib/components/TZLabel'

interface OptOutEntry {
    id: string
    recipient: string
    optOutDate: string
}

export function OptOutList({ categoryName }: { categoryName?: string }): JSX.Element {
    // Stub data - will be replaced with real data from API
    const optOutEntries: OptOutEntry[] = []

    const columns: LemonTableColumns<OptOutEntry> = [
        {
            title: 'Recipient',
            dataIndex: 'recipient',
            key: 'recipient',
        },
        {
            title: 'Opt-out date',
            dataIndex: 'optOutDate',
            key: 'optOutDate',
            render: (optOutDate) => <TZLabel time={optOutDate as string} />,
        },
    ]

    return (
        <div className="max-h-64 overflow-y-auto">
            <LemonTable
                columns={columns}
                dataSource={optOutEntries}
                rowKey="id"
                emptyState={`No opt-outs found${categoryName ? ` for ${categoryName}` : ''}`}
                size="small"
            />
        </div>
    )
}
