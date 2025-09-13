import { BindLogic, useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber } from 'lib/utils'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { Query } from '~/queries/Query/Query'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { IssueActions } from 'products/error_tracking/frontend/components/IssueActions/IssueActions'
import { IssueQueryOptions } from 'products/error_tracking/frontend/components/IssueQueryOptions/IssueQueryOptions'
import { OccurrenceSparkline } from 'products/error_tracking/frontend/components/OccurrenceSparkline'
import { IssueListTitleColumn, IssueListTitleHeader } from 'products/error_tracking/frontend/components/TableColumns'
import { useSparklineData } from 'products/error_tracking/frontend/hooks/use-sparkline-data'
import { bulkSelectLogic } from 'products/error_tracking/frontend/logics/bulkSelectLogic'
import { issuesDataNodeLogic } from 'products/error_tracking/frontend/logics/issuesDataNodeLogic'
import { errorTrackingSceneLogic } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/errorTrackingSceneLogic'
import { ERROR_TRACKING_LISTING_RESOLUTION } from 'products/error_tracking/frontend/utils'

export function IssuesList(): JSX.Element {
    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new-ErrorTrackingQuery',
    }

    const { query } = useValues(errorTrackingSceneLogic)
    const context: QueryContext = {
        columns: {
            error: {
                width: '50%',
                render: TitleColumn,
                renderTitle: TitleHeader,
            },
            occurrences: { align: 'center', render: CountColumn },
            sessions: { align: 'center', render: CountColumn },
            users: { align: 'center', render: CountColumn },
            volume: { align: 'right', renderTitle: VolumeColumnHeader, render: VolumeColumn },
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
        emptyStateHeading: 'No issues found',
        emptyStateDetail: 'Try changing the date range, changing the filters or removing the assignee.',
    }

    return (
        <BindLogic logic={issuesDataNodeLogic} props={{ key: insightVizDataNodeKey(insightProps) }}>
            <div>
                <ListOptions />
                <Query query={query} context={context} />
            </div>
        </BindLogic>
    )
}

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

const ListOptions = (): JSX.Element => {
    const { selectedIssueIds } = useValues(bulkSelectLogic)
    const { results } = useValues(issuesDataNodeLogic)

    return (
        <SceneStickyBar showBorderBottom={false}>
            {selectedIssueIds.length > 0 ? (
                <IssueActions issues={results} selectedIds={selectedIssueIds} />
            ) : (
                <IssueQueryOptions />
            )}
        </SceneStickyBar>
    )
}
