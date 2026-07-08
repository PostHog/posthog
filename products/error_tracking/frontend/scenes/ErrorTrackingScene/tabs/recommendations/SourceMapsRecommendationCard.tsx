import { useActions } from 'kea'

import { IconMagicWand } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RecommendationCard } from './RecommendationCard'
import { SourceMapsFixModal } from './SourceMapsFixModal'
import { SOURCE_MAPS_DOCS_URL, sourceMapsFixWizardLogic } from './sourceMapsFixWizardLogic'
import type { SourceMapsRecommendation } from './types'

export function SourceMapsRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: SourceMapsRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const { unresolved_pct, lookback_hours } = recommendation.meta
    const { openModal } = useActions(sourceMapsFixWizardLogic)
    const isFirstLoad = recommendation.computed_at === null

    if (isFirstLoad) {
        return (
            <RecommendationCard
                recommendationId={recommendation.id}
                title="Missing source maps"
                description="Upload source maps so JavaScript stack traces show your original source code."
                dismissed={dismissed}
            />
        )
    }

    const percent = Math.round((unresolved_pct ?? 0) * 100)

    return (
        <RecommendationCard recommendationId={recommendation.id} title="Missing source maps" dismissed={dismissed}>
            <div className="flex flex-col items-center gap-1 py-2">
                <div className="text-5xl font-bold leading-none">{percent}%</div>
                <div className="text-xs text-secondary">
                    of frames were unresolved in the last {lookback_hours} hours
                </div>
            </div>
            <div className="flex justify-center gap-2 mt-2">
                <LemonButton type="tertiary" to={SOURCE_MAPS_DOCS_URL} targetBlank>
                    Read docs
                </LemonButton>
                <LemonButton type="secondary" icon={<IconMagicWand />} onClick={() => openModal('recommendations')}>
                    <span className="rainbow-text rainbow-text-animating font-semibold">Fix with AI wizard</span>
                </LemonButton>
            </div>
            <SourceMapsFixModal />
        </RecommendationCard>
    )
}
