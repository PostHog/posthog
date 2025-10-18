import { BindLogic, useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, Link, Tooltip } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { formatCurrency } from 'lib/utils/geography/currency'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { Query } from '~/queries/Query/Query'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import {
    QueryContext,
    QueryContextColumn,
    QueryContextColumnComponent,
    QueryContextColumnTitleComponent,
} from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { IssueActions } from 'products/error_tracking/frontend/components/IssueActions/IssueActions'
import { IssueQueryOptions } from 'products/error_tracking/frontend/components/IssueQueryOptions/IssueQueryOptions'
import { issueQueryOptionsLogic } from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'
import { OccurrenceSparkline } from 'products/error_tracking/frontend/components/OccurrenceSparkline'
import { IssueListTitleColumn, IssueListTitleHeader } from 'products/error_tracking/frontend/components/TableColumns'
import { useSparklineData } from 'products/error_tracking/frontend/hooks/use-sparkline-data'
import { bulkSelectLogic } from 'products/error_tracking/frontend/logics/bulkSelectLogic'
import { issuesDataNodeLogic } from 'products/error_tracking/frontend/logics/issuesDataNodeLogic'
import { errorTrackingSceneLogic } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/errorTrackingSceneLogic'
import { ERROR_TRACKING_LISTING_RESOLUTION } from 'products/error_tracking/frontend/utils'

const VolumeColumn: QueryContextColumnComponent = (props) => {
    const record = props.record as ErrorTrackingIssue
    if (!record.aggregations) {
        throw new Error('No aggregations found')
    }
    const data = useSparklineData(record.aggregations, ERROR_TRACKING_LISTING_RESOLUTION)
    return (
        <div className="flex justify-end">
            <OccurrenceSparkline className="h-8" data={data} displayXAxis={false} />
        </div>
    )
}

const VolumeColumnHeader: QueryContextColumnTitleComponent = ({ columnName }) => {
    return (
        <div className="flex justify-between items-center min-w-64">
            <div>{columnName}</div>
        </div>
    )
}

const TitleHeader: QueryContextColumnTitleComponent = (): JSX.Element => {
    const { results } = useValues(issuesDataNodeLogic)

    return <IssueListTitleHeader results={results} />
}

const TitleColumn: QueryContextColumnComponent = (props): JSX.Element => {
    const { results } = useValues(issuesDataNodeLogic)

    return <IssueListTitleColumn results={results} {...props} />
}

const CountColumn = ({ record, columnName }: { record: unknown; columnName: string }): JSX.Element => {
    const aggregations = (record as ErrorTrackingIssue).aggregations
    const count = aggregations ? aggregations[columnName as 'occurrences' | 'sessions' | 'users'] : 0

    return (
        <span className="text-lg font-medium">
            {columnName === 'sessions' && count === 0 ? (
                <Tooltip title="No $session_id was set for any event in this issue" delayMs={0}>
                    -
                </Tooltip>
            ) : (
                humanFriendlyLargeNumber(count)
            )}
        </span>
    )
}

const defaultColumns: Record<string, QueryContextColumn> = {
    error: {
        width: '50%',
        render: TitleColumn,
        renderTitle: TitleHeader,
    },
    occurrences: { align: 'center', render: CountColumn },
    sessions: { align: 'center', render: CountColumn },
    users: { align: 'center', render: CountColumn },
    volume: { align: 'right', renderTitle: VolumeColumnHeader, render: VolumeColumn },
}

export const useIssueQueryContext = (): QueryContext => {
    const { orderBy } = useValues(issueQueryOptionsLogic)

    const columns = useMemo(() => {
        const columns = { ...defaultColumns }

        if (orderBy === 'revenue') {
            columns['revenue'] = { align: 'center', render: CurrencyColumn }
        }

        return columns
    }, [orderBy])

    return {
        columns: columns,
        showOpenEditorButton: false,
        insightProps: insightProps,
        emptyStateHeading: 'No issues found',
        emptyStateDetail: 'Try changing the date range, changing the filters or removing the assignee.',
    }
}

const insightProps: InsightLogicProps = {
    dashboardItemId: 'new-ErrorTrackingQuery',
}

export function IssuesList(): JSX.Element {
    const { orderBy } = useValues(issueQueryOptionsLogic)
    const { query } = useValues(errorTrackingSceneLogic)
    const { openSupportForm } = useActions(supportLogic)
    const context = useIssueQueryContext()

    return (
        <BindLogic logic={issuesDataNodeLogic} props={{ key: insightVizDataNodeKey(insightProps) }}>
            <div>
                <SceneStickyBar showBorderBottom={false}>
                    <ListOptions />
                    {orderBy === 'revenue' && (
                        <LemonBanner
                            type="warning"
                            action={{
                                children: 'Send feedback',
                                onClick: () =>
                                    openSupportForm({
                                        kind: 'feedback',
                                        target_area: 'error_tracking',
                                        severity_level: 'medium',
                                        isEmailFormOpen: true,
                                    }),
                                id: 'revenue-analytics-feedback-button',
                            }}
                        >
                            Revenue sorting requires setting up{' '}
                            <Link to="https://posthog.com/docs/revenue-analytics">Revenue analytics</Link>. It does not
                            yet work well for customers with a large number of persons or groups. We're keen to hear
                            feedback or any issues you have using it while we work to improve the performance
                        </LemonBanner>
                    )}
                </SceneStickyBar>
                <Query query={query} context={context} />
            </div>
        </BindLogic>
    )
}

const CurrencyColumn = ({ record }: { record: unknown }): JSX.Element => {
    const { baseCurrency } = useValues(teamLogic)
    const revenue = (record as ErrorTrackingIssue).revenue

    if (!revenue) {
        return <>-</>
    }

    return <LemonTableLink to={urls.revenueAnalytics()} title={formatCurrency(revenue, baseCurrency)} />
}

export const ListOptions = (): JSX.Element => {
    const { selectedIssueIds } = useValues(bulkSelectLogic)
    const { results } = useValues(issuesDataNodeLogic)

    if (selectedIssueIds.length > 0) {
        return <IssueActions issues={results} selectedIds={selectedIssueIds} />
    }

    return <IssueQueryOptions />
}
