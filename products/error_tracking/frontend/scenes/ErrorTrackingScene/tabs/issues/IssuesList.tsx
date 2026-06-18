import { BindLogic, useValues } from 'kea'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { Query } from '~/queries/Query/Query'
import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import {
    QueryContext,
    QueryContextColumn,
    QueryContextColumnComponent,
    QueryContextColumnTitleComponent,
} from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { IssueActions } from 'products/error_tracking/frontend/components/IssueActions/IssueActions'
import { useErrorTrackingSearchBarRedesign } from 'products/error_tracking/frontend/components/IssueFilters/SearchBarVariantToggle'
import { IssueQueryOptions } from 'products/error_tracking/frontend/components/IssueQueryOptions/IssueQueryOptions'
import { IssueListTitleColumn, IssueListTitleHeader } from 'products/error_tracking/frontend/components/TableColumns'
import { bulkSelectLogic } from 'products/error_tracking/frontend/logics/bulkSelectLogic'
import { issuesDataNodeLogic } from 'products/error_tracking/frontend/logics/issuesDataNodeLogic'
import { errorTrackingSceneLogic } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/errorTrackingSceneLogic'

import { IssueCountColumn, IssueCountCell, IssueVolumeCell } from './issueListCells'

const VolumeColumn: QueryContextColumnComponent = (props) => {
    return <IssueVolumeCell record={props.record as ErrorTrackingIssue} />
}

const VolumeColumnHeader: QueryContextColumnTitleComponent = ({ columnName }) => {
    return (
        <div className="flex w-full min-w-0 justify-center items-center">
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
    return <IssueCountCell record={record as ErrorTrackingIssue} columnName={columnName as IssueCountColumn} />
}

const ISSUE_COUNT_COLUMN_WIDTH = 'clamp(4.75rem, 5vw, 5.5rem)'

const defaultColumns: Record<string, QueryContextColumn> = {
    error: {
        width: '50%',
        render: TitleColumn,
        renderTitle: TitleHeader,
    },
    occurrences: { align: 'center', width: ISSUE_COUNT_COLUMN_WIDTH, render: CountColumn },
    sessions: { align: 'center', width: ISSUE_COUNT_COLUMN_WIDTH, render: CountColumn },
    users: { align: 'center', width: ISSUE_COUNT_COLUMN_WIDTH, render: CountColumn },
    volume: {
        align: 'center',
        width: 'clamp(12rem, 20vw, 13rem)',
        renderTitle: VolumeColumnHeader,
        render: VolumeColumn,
    },
}

export const useIssueQueryContext = (): QueryContext => {
    return {
        columns: defaultColumns,
        showOpenEditorButton: false,
        insightProps: insightProps,
        emptyStateHeading: 'No issues found',
        emptyStateDetail: 'Try changing the date range, changing the filters or removing the assignee.',
    }
}

export const insightProps: InsightLogicProps = {
    dashboardItemId: 'new-ErrorTrackingQuery',
}

export function IssuesList(): JSX.Element {
    const { query } = useValues(errorTrackingSceneLogic)
    const context = useIssueQueryContext()
    const newSearchBar = useErrorTrackingSearchBarRedesign()

    // The redesigned layout binds issuesDataNodeLogic and renders the filter bar in the
    // scene, so the list is just the table. The legacy layout owns both itself.
    if (newSearchBar) {
        return (
            <div data-attr="error-tracking-issue-row">
                <Query query={query} context={context} />
            </div>
        )
    }

    return (
        <BindLogic
            logic={issuesDataNodeLogic}
            props={{ key: insightVizDataNodeKey(insightProps), query: query.source }}
        >
            <SceneStickyBar showBorderBottom={false}>
                <ListOptions />
            </SceneStickyBar>

            <div data-attr="error-tracking-issue-row">
                <Query query={query} context={context} />
            </div>
        </BindLogic>
    )
}

const ListOptions = (): JSX.Element => {
    const { selectedIssueIds } = useValues(bulkSelectLogic)
    const { results } = useValues(issuesDataNodeLogic)

    if (selectedIssueIds.length > 0) {
        return <IssueActions issues={results} selectedIds={selectedIssueIds} />
    }

    return <IssueQueryOptions />
}
