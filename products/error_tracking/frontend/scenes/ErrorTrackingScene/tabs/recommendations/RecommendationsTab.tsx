import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { AlertsRecommendationCard } from './AlertsRecommendationCard'
import { CrossSellRecommendationCard } from './CrossSellRecommendationCard'
import { ExceptionAutocaptureRecommendationCard } from './ExceptionAutocaptureRecommendationCard'
import {
    isAlertsRecommendation,
    isCrossSellRecommendation,
    isExceptionAutocaptureRecommendation,
    isWeeklyDigestRecommendation,
    recommendationsTabLogic,
} from './recommendationsTabLogic'
import type { ErrorTrackingRecommendation } from './types'
import { WeeklyDigestRecommendationCard } from './WeeklyDigestRecommendationCard'

function renderCard(recommendation: ErrorTrackingRecommendation, dismissed: boolean): JSX.Element | null {
    if (isCrossSellRecommendation(recommendation)) {
        return <CrossSellRecommendationCard recommendation={recommendation} dismissed={dismissed} />
    }
    if (isAlertsRecommendation(recommendation)) {
        return <AlertsRecommendationCard recommendation={recommendation} dismissed={dismissed} />
    }
    if (isWeeklyDigestRecommendation(recommendation)) {
        return <WeeklyDigestRecommendationCard recommendation={recommendation} dismissed={dismissed} />
    }
    if (isExceptionAutocaptureRecommendation(recommendation)) {
        return <ExceptionAutocaptureRecommendationCard recommendation={recommendation} dismissed={dismissed} />
    }
    return null
}

function RecommendationGrid({
    recommendations,
    dismissed,
    faded,
}: {
    recommendations: ErrorTrackingRecommendation[]
    dismissed: boolean
    faded?: boolean
}): JSX.Element {
    return (
        <div className={`columns-1 md:columns-2 xl:columns-3 gap-4 ${faded ? 'opacity-60' : ''}`}>
            {recommendations.map((recommendation) => (
                <div key={recommendation.id} className="break-inside-avoid mb-4">
                    {renderCard(recommendation, dismissed)}
                </div>
            ))}
        </div>
    )
}

function CollapsibleSection({
    label,
    count,
    expanded,
    onToggle,
    children,
}: {
    label: string
    count: number
    expanded: boolean
    onToggle: () => void
    children: React.ReactNode
}): JSX.Element {
    return (
        <div>
            <button
                type="button"
                className="flex items-center gap-1 text-xs text-muted hover:text-primary cursor-pointer bg-transparent border-0 p-0"
                onClick={onToggle}
                aria-expanded={expanded}
            >
                <IconChevronRight className={`text-sm ${expanded ? 'rotate-90' : ''}`} />
                {count} {label}
            </button>
            {expanded && <div className="mt-2">{children}</div>}
        </div>
    )
}

export function RecommendationsTab(): JSX.Element {
    const {
        recommendations,
        recommendationsLoading,
        pendingRecommendations,
        completedRecommendations,
        ignoredRecommendations,
        completedExpanded,
        dismissedExpanded,
    } = useValues(recommendationsTabLogic)
    const { toggleCompletedExpanded, toggleDismissedExpanded } = useActions(recommendationsTabLogic)

    if (recommendationsLoading && recommendations.length === 0) {
        return (
            <div className="flex justify-center py-8">
                <Spinner />
            </div>
        )
    }

    if (recommendations.length === 0) {
        return (
            <div className="border rounded-lg bg-surface-primary p-4 text-secondary text-sm">
                No recommendations right now — everything's looking good!
            </div>
        )
    }

    const hasAnyVisible =
        pendingRecommendations.length > 0 || completedRecommendations.length > 0 || ignoredRecommendations.length > 0

    return (
        <div className="flex flex-col gap-4">
            {pendingRecommendations.length > 0 && (
                <RecommendationGrid recommendations={pendingRecommendations} dismissed={false} />
            )}

            {pendingRecommendations.length === 0 && hasAnyVisible && (
                <div className="border rounded-lg bg-surface-primary p-4 text-secondary text-sm">
                    No pending recommendations — everything's looking good!
                </div>
            )}

            {completedRecommendations.length > 0 && (
                <CollapsibleSection
                    label="completed"
                    count={completedRecommendations.length}
                    expanded={completedExpanded}
                    onToggle={toggleCompletedExpanded}
                >
                    <RecommendationGrid recommendations={completedRecommendations} dismissed={false} faded />
                </CollapsibleSection>
            )}

            {ignoredRecommendations.length > 0 && (
                <CollapsibleSection
                    label="dismissed"
                    count={ignoredRecommendations.length}
                    expanded={dismissedExpanded}
                    onToggle={toggleDismissedExpanded}
                >
                    <RecommendationGrid recommendations={ignoredRecommendations} dismissed faded />
                </CollapsibleSection>
            )}
        </div>
    )
}
