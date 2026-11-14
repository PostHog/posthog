// PROTOTYPE (ticket #320), throwaway: invented rows standing in for a team that already sends.
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { CodeBadge } from '../code/CodeBadge'

interface Row {
    id: string
    name: string
    code: boolean
    sent: number
    updated: string
}

const ROWS: Row[] = [
    { id: '1', name: 'password-reset', code: true, sent: 412, updated: '2 hours ago' },
    { id: '2', name: 'sign-in-code', code: true, sent: 1290, updated: '10 minutes ago' },
    { id: '3', name: 'Invoice receipt', code: false, sent: 87, updated: '3 days ago' },
]

export function PrototypeEmailsTable(): JSX.Element {
    return (
        <LemonTable<Row>
            dataSource={ROWS}
            rowKey="id"
            columns={[
                {
                    title: 'Name',
                    key: 'name',
                    render: (_, row) => (
                        <span className="flex items-center gap-1 font-semibold py-1">
                            <span className={row.code ? 'font-mono' : undefined}>{row.name}</span>
                            {row.code ? <CodeBadge sourceUrl={null} /> : null}
                        </span>
                    ),
                },
                { title: 'Sent, last 7 days', key: 'sent', render: (_, row) => row.sent },
                { title: 'Created by', key: 'by', render: (_, row) => (row.code ? 'Your code' : 'Jane Doe') },
                { title: 'Updated', key: 'updated', render: (_, row) => row.updated },
            ]}
        />
    )
}
