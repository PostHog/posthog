import { BindLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

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
import { IssueQueryOptions } from 'products/error_tracking/frontend/components/IssueQueryOptions/IssueQueryOptions'
import { IssueListTitleColumn, IssueListTitleHeader } from 'products/error_tracking/frontend/components/TableColumns'
import { errorTrackingVolumeSparklineLogic } from 'products/error_tracking/frontend/components/VolumeSparkline/errorTrackingVolumeSparklineLogic'
import {
    formatCompactVolumeHoverDate,
    formatCompactVolumeHoverOccurrences,
} from 'products/error_tracking/frontend/components/VolumeSparkline/formatCompactVolumeHover'
import { VolumeSparkline } from 'products/error_tracking/frontend/components/VolumeSparkline/VolumeSparkline'
import { applyVolumeSpikeHighlights, useSparklineData } from 'products/error_tracking/frontend/hooks/use-sparkline-data'
import { batchSpikeEventsLogic } from 'products/error_tracking/frontend/logics/batchSpikeEventsLogic'
import { bulkSelectLogic } from 'products/error_tracking/frontend/logics/bulkSelectLogic'
import { issuesDataNodeLogic } from 'products/error_tracking/frontend/logics/issuesDataNodeLogic'
import { errorTrackingSceneLogic } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/errorTrackingSceneLogic'
import { ERROR_TRACKING_LISTING_RESOLUTION } from 'products/error_tracking/frontend/utils'

const VolumeColumn: QueryContextColumnComponent = (props) => {
    const record = props.record as ErrorTrackingIssue
    if (!record.aggregations) {
        throw new Error('No aggregations found')
    }
    const sparklineKey = record.id ?? 'issue-unknown'
    const baseData = useSparklineData(record.aggregations, ERROR_TRACKING_LISTING_RESOLUTION)
    const { spikeEventsByIssueId } = useValues(batchSpikeEventsLogic)
    const spikeEvents = record.id ? (spikeEventsByIssueId[record.id] ?? []) : []
    const data = useMemo(() => applyVolumeSpikeHighlights(baseData, spikeEvents), [baseData, spikeEvents])

    const { hoveredDatum, isBarHighlighted } = useValues(errorTrackingVolumeSparklineLogic({ sparklineKey }))

    return (
        <div className="flex w-full min-w-0 justify-center">
            <div className="flex w-56 max-w-full min-w-0 flex-col">
                <div className="h-12 min-h-12 w-full">
                    <VolumeSparkline
                        className="h-full"
                        data={data}
                        layout="compact"
                        xAxis="minimal"
                        sparklineKey={sparklineKey}
                    />
                </div>
                <div
                    className={cn(
                        'flex h-3 w-full items-center justify-between gap-1 px-px text-[9px] leading-none text-muted',
                        isBarHighlighted ? 'opacity-100' : 'opacity-0'
                    )}
                >
                    <span className="min-w-0 truncate">
                        {hoveredDatum ? formatCompactVolumeHoverDate(hoveredDatum) : '\u00a0'}
                    </span>
                    <span className="min-w-0 shrink-0 text-right tabular-nums">
                        {hoveredDatum ? formatCompactVolumeHoverOccurrences(hoveredDatum) : '\u00a0'}
                    </span>
                </div>
            </div>
        </div>
    )
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

const insightProps: InsightLogicProps = {
    dashboardItemId: 'new-ErrorTrackingQuery',
}

export function IssuesList(): JSX.Element {
    const { query } = useValues(errorTrackingSceneLogic)
    const context = useIssueQueryContext()

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

export const ListOptions = (): JSX.Element => {
    const { selectedIssueIds } = useValues(bulkSelectLogic)
    const { results } = useValues(issuesDataNodeLogic)

    if (selectedIssueIds.length > 0) {
        return <IssueActions issues={results} selectedIds={selectedIssueIds} />
    }

    return <IssueQueryOptions />
}
