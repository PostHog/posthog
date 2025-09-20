import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTableColumns, Spinner } from '@posthog/lemon-ui'

import { IconRefresh } from 'lib/lemon-ui/icons'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingCorrelatedIssue } from '~/queries/schema/schema-general'

import { IssueActions } from '../../../../components/IssueActions/IssueActions'
import { IssueListTitleColumn, IssueListTitleHeader } from '../../../../components/TableColumns'
import { bulkSelectLogic } from '../../../../logics/bulkSelectLogic'
import { errorTrackingImpactListLogic } from './errorTrackingImpactListLogic'

export const scene: SceneExport = {
    component: ImpactList,
    logic: errorTrackingImpactListLogic,
}

export function ImpactList(): JSX.Element | null {
    const { initialState } = useValues(errorTrackingImpactListLogic)

    if (initialState) {
        return null
    }

    return (
        <div>
            <Options />
            <Table />
        </div>
    )
}

const Table = (): JSX.Element => {
    const { issues, issuesLoading } = useValues(errorTrackingImpactListLogic)

    const columns: LemonTableColumns<ErrorTrackingCorrelatedIssue> = [
        {
            title: <IssueListTitleHeader results={issues} />,
            render: function RenderTitle(_, record, recordIndex) {
                return <IssueListTitleColumn results={issues} record={record} recordIndex={recordIndex} />
            },
        },
        {
            title: 'Impact',
            key: 'impact',
            align: 'center',
            tooltip:
                'The impact is measured by the odds ratio, which indicates the likelihood of this issue causing the event not to occur.',
            sorter: (a, b) => a.odds_ratio - b.odds_ratio,
            render: function RenderImpact(_, record) {
                return <span className="text-lg font-medium">{humanFriendlyLargeNumber(record.odds_ratio)}</span>
            },
            width: '20%',
        },
        {
            title: 'Population',
            key: 'population',
            align: 'center',
            sorter: (a, b) => population(a) - population(b),
            render: function RenderPopulation(_, record) {
                return <span className="text-lg font-medium">{humanFriendlyLargeNumber(population(record))}</span>
            },
            width: '20%',
        },
    ]

    return (
        <LemonTable
            columns={columns}
            loading={issuesLoading}
            dataSource={issues}
            emptyState={
                <InsightEmptyState
                    heading="No issues found"
                    detail="It looks like there are no issues affecting this event, please try a different one."
                />
            }
            expandable={{
                noIndent: true,
                expandedRowRender: function RenderExpandedRow(record) {
                    return (
                        <LemonTable
                            embedded
                            stealth
                            columns={[
                                { dataIndex: 'row' },
                                { title: record.event, dataIndex: 'event' },
                                { title: `No ${record.event}`, dataIndex: 'no_event' },
                            ]}
                            dataSource={[
                                {
                                    row: 'Exception occurred',
                                    event: record.population.both,
                                    no_event: record.population.exception_only,
                                },
                                {
                                    row: 'No exception',
                                    event: record.population.success_only,
                                    no_event: record.population.neither,
                                },
                            ]}
                        />
                    )
                },
            }}
        />
    )
}

export const Options = (): JSX.Element => {
    const { selectedIssueIds } = useValues(bulkSelectLogic)
    const { issues } = useValues(errorTrackingImpactListLogic)

    return (
        <div className="sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-primary">
            {selectedIssueIds.length > 0 ? <IssueActions issues={issues} selectedIds={selectedIssueIds} /> : <Reload />}
        </div>
    )
}

const Reload = (): JSX.Element => {
    const { issuesLoading } = useValues(errorTrackingImpactListLogic)
    const { loadIssues } = useActions(errorTrackingImpactListLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            onClick={() => loadIssues()}
            disabledReason={issuesLoading ? 'Loading issues...' : undefined}
            icon={issuesLoading ? <Spinner textColored /> : <IconRefresh />}
        >
            {issuesLoading ? 'Cancel' : 'Reload'}
        </LemonButton>
    )
}

const population = (issue: ErrorTrackingCorrelatedIssue): number => {
    return Object.values(issue.population).reduce((acc, val) => acc + val, 0)
}
