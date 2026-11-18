import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { QuillSetupFactsTable } from './QuillSetupFactsTable'
import type { SetupFact } from './setupFact'

export type { SetupFact } from './setupFact'

export function SetupFactsTable({ facts }: { facts: SetupFact[] }): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    if (todayRailNav && resultsRedesign) {
        return <QuillSetupFactsTable facts={facts} />
    }
    return (
        <LemonTable
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
