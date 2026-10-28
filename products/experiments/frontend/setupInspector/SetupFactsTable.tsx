import { LemonOrQuillTable } from 'lib/lemon-ui/LemonTable/LemonOrQuillTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export interface SetupFact {
    label: string
    value: React.ReactNode
    /** The field's meaning, shown on hover over the label. */
    help?: string
}

export function SetupFactsTable({ facts }: { facts: SetupFact[] }): JSX.Element {
    return (
        <LemonOrQuillTable
            size="small"
            showHeader={false}
            rowKey="label"
            dataSource={facts}
            columns={[
                {
                    key: 'label',
                    width: '40%',
                    render: (_, fact) =>
                        fact.help ? (
                            <Tooltip title={fact.help}>
                                <span className="underline decoration-dotted">{fact.label}</span>
                            </Tooltip>
                        ) : (
                            <span>{fact.label}</span>
                        ),
                },
                {
                    key: 'value',
                    render: (_, fact) => <span translate="no">{fact.value}</span>,
                },
            ]}
        />
    )
}
