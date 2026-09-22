import { BindLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
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
import { issueQueryOptionsLogic } from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'
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

import { IssuesFilters } from './IssuesFilters'

const VolumeColumn: QueryContextColumnComponent = (props) => {
    const record = props.record as ErrorTrackingIssue
    const sparklineKey = record.id ?? 'issue-unknown'
    const baseData = useSparklineData(record.aggregations, ERROR_TRACKING_LISTING_RESOLUTION)
    const { spikeEventsByIssueId } = useValues(batchSpikeEventsLogic)
    const { orderBy } = useValues(issueQueryOptionsLogic)
    const spikeEvents = record.id ? (spikeEventsByIssueId[record.id] ?? []) : []
    const data = useMemo(() => applyVolumeSpikeHighlights(baseData, spikeEvents), [baseData, spikeEvents])

    const { hoveredDatum, isBarHighlighted } = useValues(errorTrackingVolumeSparklineLogic({ sparklineKey }))

    return (
        <div className="flex w-full min-w-0 justify-center">
            <div className="flex w-56 max-w-full min-w-0 flex-col">
                <div className="h-20 min-h-20 w-full">
                    <VolumeSparkline
                        className="h-full"
                        data={data}
                        layout="compact"
                        xAxis="minimal"
                        sparklineKey={sparklineKey}
                    />
                </div>
                <div className="flex h-4 w-full items-center justify-between gap-1 px-1 text-[10px] leading-none text-muted">
                    {isBarHighlighted && hoveredDatum ? (
                        <>
                            <span className="min-w-0 truncate">{formatCompactVolumeHoverDate(hoveredDatum)}</span>
                            <span className="min-w-0 shrink-0 text-right tabular-nums">
                                {formatCompactVolumeHoverOccurrences(hoveredDatum)}
                            </span>
                        </>
                    ) : (
                        <div className="flex w-full items-center justify-end gap-1">
                            {orderBy === 'first_seen' ? (
                                <>
                                    <span className="whitespace-nowrap">{dayjs(record.first_seen).fromNow()}</span>
                                    <IconArrowRight className="size-2.5 shrink-0" />
                                </>
                            ) : null}
                            {record.last_seen ? (
                                <span className="whitespace-nowrap text-right">
                                    {dayjs(record.last_seen).fromNow()}
                                </span>
                            ) : null}
                        </div>
                    )}
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
            {/* first:-mt-4 tucks the bar flush under the tab bar, but only when no banner
                renders above — an unconditional -mt-4 would cover the banner's bottom edge */}
            <SceneStickyBar className="first:-mt-4" showBorderBottom={false}>
                <IssuesFilters />
                <ListOptions />
            </SceneStickyBar>

            <div data-attr="error-tracking-issue-row">
                <Query query={query} context={context} />
            </div>
        </BindLogic>
    )
}

export const ListOptions = (): JSX.Element | null => {
    const { selectedIssueIds } = useValues(bulkSelectLogic)
    const { results } = useValues(issuesDataNodeLogic)

    if (selectedIssueIds.length > 0) {
        return <IssueActions issues={results} selectedIds={selectedIssueIds} />
    }

    return null
}
