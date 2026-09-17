import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { BREAKDOWN_LABELS } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'
import {
    MARKETING_ANALYTICS_RETENTION_COLLECTION_ID,
    marketingRetentionLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingRetentionLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    MarketingAnalyticsRetentionQuery,
    MarketingAnalyticsRetentionQueryResponse,
} from '~/queries/schema/schema-general'

import { RetentionReturnTable } from './RetentionReturnTable'

export function RetentionResults({
    query,
    attachTo,
}: {
    query: MarketingAnalyticsRetentionQuery
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element {
    const logic = dataNodeLogic({
        query,
        key: 'MarketingRetention',
        dataNodeCollectionId: MARKETING_ANALYTICS_RETENTION_COLLECTION_ID,
    })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)
    const { breakdownBy, onlyNewUsers } = useValues(marketingRetentionLogic)
    useAttachedLogic(logic, attachTo)
    const retentionResponse = response as MarketingAnalyticsRetentionQueryResponse | undefined

    if (responseError) {
        return <InsightErrorState query={query} onRetry={loadData} />
    }

    return (
        <RetentionReturnTable
            rows={retentionResponse?.summary ?? []}
            dimensionLabel={BREAKDOWN_LABELS[breakdownBy]}
            loading={responseLoading || !retentionResponse}
            compare={query.comparePreviousPeriod ?? false}
            onlyNewUsers={onlyNewUsers}
        />
    )
}
