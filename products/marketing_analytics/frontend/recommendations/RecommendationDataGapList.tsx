import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { RecommendationDataGap } from './recommendations'

export function RecommendationDataGapList({ gaps }: { gaps: RecommendationDataGap[] }): JSX.Element {
    const sourceIds = [...new Set(gaps.map((gap) => gap.sourceId))]
    return (
        <div className="flex w-[28rem] max-w-[90vw] flex-col gap-2 p-1">
            <div className="px-2 pt-1">
                <strong>Improve recommendations</strong>
                <p className="mb-0 text-secondary">Some rules need tables that these sources do not sync yet.</p>
            </div>
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
                            >
                                Manage source
                            </LemonButton>
                        </div>
                        <ul className="m-0 flex list-disc flex-col gap-1 pl-4 text-xs text-secondary">
                            {sourceGaps.map((gap) => (
                                <li key={gap.table}>{gap.description}</li>
                            ))}
                        </ul>
                    </div>
                )
            })}
        </div>
    )
}
