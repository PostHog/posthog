import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { RecommendationsActionLocation } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { RecommendationDataGapDescription } from './RecommendationDataGapDescription'
import { RecommendationDataGap, ServerDataGap } from './recommendations'
import { RecommendationServerDataGap } from './RecommendationServerDataGap'
import { recommendationsLogic } from './recommendationsLogic'

export function RecommendationDataGapList({
    gaps,
    serverGaps,
    location,
}: {
    gaps: RecommendationDataGap[]
    serverGaps: ServerDataGap[]
    location: RecommendationsActionLocation
}): JSX.Element {
    const { reportRecommendationsActionClicked } = useActions(recommendationsLogic)
    const sourceIds = [...new Set(gaps.map((gap) => gap.sourceId))]
    return (
        <div className="flex w-[28rem] max-w-[90vw] flex-col gap-2 p-1">
            <strong className="px-2 pt-1">Improve recommendations</strong>
            {serverGaps.map((gap) => (
                <RecommendationServerDataGap key={`${gap.kind}-${gap.sourceName}`} gap={gap} location={location} />
            ))}
            {gaps.length > 0 && (
                <p className="mb-0 px-2 text-secondary">Some rules need tables that these sources do not sync yet.</p>
            )}
            {sourceIds.map((sourceId) => {
                const sourceGaps = gaps.filter((gap) => gap.sourceId === sourceId)
                return (
                    <div key={sourceId} className="flex flex-col gap-2 rounded border px-3 py-2">
                        <div className="flex items-center justify-between gap-3">
                            <span className="font-semibold">{sourceGaps[0].sourceName}</span>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                to={urls.dataWarehouseSource(`managed-${sourceId}`)}
                                data-attr="marketing-recommendations-data-gap-manage-source"
                                onClick={() => reportRecommendationsActionClicked('manage_source', location)}
                            >
                                Manage source
                            </LemonButton>
                        </div>
                        <ul className="m-0 flex list-disc flex-col gap-1 pl-4 text-xs text-secondary">
                            {sourceGaps.map((gap) => (
                                <li key={gap.table}>
                                    <RecommendationDataGapDescription gap={gap} />
                                </li>
                            ))}
                        </ul>
                    </div>
                )
            })}
        </div>
    )
}
