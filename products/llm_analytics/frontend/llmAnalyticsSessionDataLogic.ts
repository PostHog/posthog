import { connect, kea, path, props, selectors } from 'kea'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, TracesQueryResponse } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import type { llmAnalyticsSessionDataLogicType } from './llmAnalyticsSessionDataLogicType'
import { llmAnalyticsSessionLogic } from './llmAnalyticsSessionLogic'

export interface SessionDataLogicProps {
    sessionId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
}

function getDataNodeLogicProps({ sessionId, query, cachedResults }: SessionDataLogicProps): DataNodeLogicProps {
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Session.${sessionId}`,
        dataNodeCollectionId: sessionId,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: sessionId,
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

export const llmAnalyticsSessionDataLogic = kea<llmAnalyticsSessionDataLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsSessionDataLogic']),
    props({} as SessionDataLogicProps),
    connect((props: SessionDataLogicProps) => ({
        values: [
            llmAnalyticsSessionLogic,
            ['sessionId'],
            dataNodeLogic(getDataNodeLogicProps(props)),
            ['response', 'responseLoading', 'responseError'],
        ],
    })),
    selectors({
        traces: [
            (s) => [s.response],
            (response) => {
                const tracesResponse = response as TracesQueryResponse | null
                return tracesResponse?.results || []
            },
        ],
    }),
])
