import { useActions, useValues } from 'kea'

import { TileId } from 'scenes/web-analytics/common'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendsQuery, WebStatsTableQuery, WebStatsTableQueryResponse } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { ConversionValueByBreakdown, conversionValueRows } from './conversionValueRows'
import { MarketingBreakdownTable } from './MarketingBreakdownTable'
import {
    AVG_CONVERSION_VALUE_COLUMN,
    CONVERSIONS_COLUMN,
    CONVERSION_RATE_COLUMN,
    CONVERSION_VALUE_COLUMN,
    SESSIONS_COLUMN,
} from './webStatsColumns'
import { WebStatsRow, webStatsRows } from './webStatsRows'

const FOOTNOTE =
    'Each row counts the conversions of sessions that started on that channel. Conversion rate divides converting people by visitors.'

const NO_VALUES: Map<string, ConversionValueByBreakdown> = new Map()

export interface ConversionBreakdownTableProps {
    query: WebStatsTableQuery
}

/** The value lives in its own query because WebStatsTableQuery never returns the goal's value
 * property. */
export function ConversionBreakdownTable({ query }: ConversionBreakdownTableProps): JSX.Element {
    const { conversionValueBreakdownQuery } = useValues(marketingDashboardLogic)

    // The branch picks which component mounts, so neither one calls a hook conditionally.
    return conversionValueBreakdownQuery ? (
        <WithConversionValue statsQuery={query} valueQuery={conversionValueBreakdownQuery} />
    ) : (
        <ConversionTable statsQuery={query} values={NO_VALUES} withValueColumns={false} />
    )
}

function WithConversionValue({
    statsQuery,
    valueQuery,
}: {
    statsQuery: WebStatsTableQuery
    valueQuery: TrendsQuery
}): JSX.Element {
    const logic = dataNodeLogic({
        query: valueQuery,
        key: 'marketing-dashboard-conversion-value-breakdown',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response } = useValues(logic)
    const results = (response as { results?: TrendResult[] } | undefined)?.results

    // Deliberately not gating on this query's loading or error state: the value is supplementary,
    // so a slow or failed value query leaves two cells empty rather than holding up the table.
    return <ConversionTable statsQuery={statsQuery} values={conversionValueRows(results)} withValueColumns />
}

function ConversionTable({
    statsQuery,
    values,
    withValueColumns,
}: {
    statsQuery: WebStatsTableQuery
    values: Map<string, ConversionValueByBreakdown>
    withValueColumns: boolean
}): JSX.Element {
    const logic = dataNodeLogic({
        query: statsQuery,
        key: 'marketing-dashboard-conversion-table',
        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)

    const rows: WebStatsRow[] = webStatsRows(response as WebStatsTableQueryResponse | undefined).map((row) => {
        const value = values.get(row.breakdownValue)
        return value ? { ...row, conversion_value: value.total, avg_conversion_value: value.average } : row
    })

    return (
        <MarketingBreakdownTable
            tileId={TileId.MARKETING_CONVERSION_TABLE}
            titlePrefix="Conversion by"
            rows={rows}
            rowKey={(row) => row.breakdownValue}
            breakdownValue={(row) => row.breakdownValue}
            columns={[
                SESSIONS_COLUMN,
                CONVERSIONS_COLUMN,
                CONVERSION_RATE_COLUMN,
                ...(withValueColumns ? [CONVERSION_VALUE_COLUMN, AVG_CONVERSION_VALUE_COLUMN] : []),
            ]}
            defaultSortKey="total_conversions"
            loading={responseLoading}
            error={!!responseError}
            onRetry={() => loadData('force_async')}
            emptyState="No conversions in this range."
            exportFilename="marketing-conversion"
            footnote={FOOTNOTE}
        />
    )
}
