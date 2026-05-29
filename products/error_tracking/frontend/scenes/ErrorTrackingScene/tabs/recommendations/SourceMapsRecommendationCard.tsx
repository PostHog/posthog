import { useActions } from 'kea'

import { IconMagicWand } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RecommendationCard } from './RecommendationCard'
import { SourceMapsFixModal } from './SourceMapsFixModal'
import { sourceMapsFixWizardLogic } from './sourceMapsFixWizardLogic'
import type { SourceMapsRecommendation } from './types'

const SOURCE_MAPS_DOCS_URL = 'https://posthog.com/docs/error-tracking/upload-source-maps'

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
                    of JavaScript frames were unresolved in the last {lookback_hours} hours
                </div>
            </div>
            <div className="flex items-center gap-2 mt-2 max-w-xs mx-auto">
                <div className="flex-1">
                    <LemonButton type="primary" icon={<IconMagicWand />} onClick={openModal} fullWidth center>
                        Fix with wizard
                    </LemonButton>
                </div>
                <div className="flex-1">
                    <LemonButton type="secondary" to={SOURCE_MAPS_DOCS_URL} targetBlank fullWidth center>
                        Docs
                    </LemonButton>
                </div>
            </div>
            <SourceMapsFixModal />
        </RecommendationCard>
    )
}
