import { BindLogic, useMountedLogic } from 'kea'
import { useMemo } from 'react'

import 'lib/components/Cards/InsightCard/InsightCard.scss'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataCollectionId, insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import type { AnyResponseType, InsightVizNode } from '~/queries/schema/schema-general'
import type { QueryContext } from '~/queries/types'
import { InsightLogicProps, InsightType } from '~/types'

import { TrendInsight } from 'products/product_analytics/frontend/insights/trends/Trends'

const PREVIEW_CONTEXT: QueryContext<InsightVizNode> = { hideAxes: true }

// A chart-only render of a query with a known result: the same logics the insight editor mounts, minus the
// display chrome, and with loading disabled so a tile never issues a request of its own.
export function ChartPreviewCanvas({
    embedded = true,
    query,
    response,
    uniqueKey,
}: {
    embedded?: boolean
    query: InsightVizNode
    response: AnyResponseType
    uniqueKey: string
}): JSX.Element {
    const insightProps = useMemo(
        (): InsightLogicProps<InsightVizNode> => ({
            // The `new-AdHoc.` prefix is what makes insightDataLogic take the query from props.
            dashboardItemId: `new-AdHoc.${uniqueKey}`,
            query,
            doNotLoad: true,
            dataNodeCollectionId: uniqueKey,
        }),
        [query, uniqueKey]
    )
    const dataNodeLogicProps = useMemo((): DataNodeLogicProps => {
        const vizKey = insightVizDataNodeKey(insightProps)
        return {
            query: query.source,
            key: vizKey,
            cachedResults: response,
            doNotLoad: true,
            dataNodeCollectionId: insightVizDataCollectionId(insightProps, vizKey),
        }
    }, [insightProps, query.source, response])

    useMountedLogic(dataNodeLogic(dataNodeLogicProps))
    useMountedLogic(insightLogic(insightProps as InsightLogicProps))
    useMountedLogic(insightDataLogic(insightProps as InsightLogicProps))
    useMountedLogic(insightVizDataLogic(insightProps as InsightLogicProps))

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={insightDataLogic} props={insightProps}>
                <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                    <BindLogic logic={insightVizDataLogic} props={insightProps}>
                        <TrendInsight
                            view={InsightType.TRENDS}
                            embedded={embedded}
                            inSharedMode
                            context={PREVIEW_CONTEXT}
                        />
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
