import { useActions, useValues } from 'kea'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingCorrelatedIssue } from '~/queries/schema/schema-general'

import { EventName } from 'products/actions/frontend/components/EventName'

import { ErrorTrackingSetupPrompt } from '../components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { BulkActions } from '../components/IssueActions/BulkActions'
import { IssueListTitleColumn, IssueListTitleHeader } from '../components/TableColumns'
import { errorTrackingBulkSelectLogic } from '../errorTrackingBulkSelectLogic'
import { errorTrackingImpactSceneLogic } from './errorTrackingImpactSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingImpactScene,
    logic: errorTrackingImpactSceneLogic,
}

export function ErrorTrackingImpactScene(): JSX.Element | null {
    const { completedInitialLoad, issuesLoading } = useValues(errorTrackingImpactSceneLogic)
    const hasIssueCorrelation = useFeatureFlag('ERROR_TRACKING_ISSUE_CORRELATION')

    return hasIssueCorrelation ? (
        <ErrorTrackingSetupPrompt>
            {!issuesLoading && !completedInitialLoad ? (
                <InitialState />
            ) : (
                <div className="px-4">
                    <Options />
                    <Table />
                </div>
            )}
        </ErrorTrackingSetupPrompt>
    ) : null
}

const Table = (): JSX.Element => {
    const { issues, issuesLoading } = useValues(errorTrackingImpactSceneLogic)

    const columns: LemonTableColumns<ErrorTrackingCorrelatedIssue> = [
        {
            title: <IssueListTitleHeader results={issues} columnName="Issue" />,
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
        />
    )
}

const InitialState = (): JSX.Element => {
    const { event } = useValues(errorTrackingImpactSceneLogic)
    const { setEvent } = useActions(errorTrackingImpactSceneLogic)

    return (
        <div className="flex flex-col flex-1 items-center mt-24 text-center mb-1">
            <h2 className="text-xl font-bold">Understand the impact of issues</h2>
            <div className="text-sm text-secondary mb-2">
                See what issues are causing the most impact on your conversion, activation or any other event you're
                tracking in PostHog.
            </div>
            <EventName value={event} onChange={setEvent} allEventsOption="clear" placement="bottom" />
        </div>
    )
}

export const Options = (): JSX.Element => {
    const { selectedIssueIds } = useValues(errorTrackingBulkSelectLogic)
    const { event, issues } = useValues(errorTrackingImpactSceneLogic)
    const { setEvent } = useActions(errorTrackingImpactSceneLogic)

    return (
        <div className="sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-primary">
            {selectedIssueIds.length > 0 ? (
                <BulkActions issues={issues} selectedIds={selectedIssueIds} />
            ) : (
                <EventName value={event} onChange={setEvent} allEventsOption="clear" placement="bottom" />
            )}
        </div>
    )
}

const population = (issue: ErrorTrackingCorrelatedIssue): number => {
    return Object.values(issue.population).reduce((acc, val) => acc + val, 0)
}
