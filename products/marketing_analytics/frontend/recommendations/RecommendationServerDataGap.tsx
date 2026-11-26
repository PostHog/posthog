import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { RecommendationsActionLocation } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { DataGapNavigation, ServerDataGap } from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'

const NAVIGATION_LABELS: Record<DataGapNavigation, string> = {
    edit_conversion_goals: 'Edit conversion goals',
    open_utm_audit: 'Open UTM audit',
}

function GapAction({
    gap,
    location,
}: {
    gap: ServerDataGap
    location: RecommendationsActionLocation
}): JSX.Element | null {
    const { setupEnabled } = useValues(recommendationsLogic)
    const { openDataGapTarget, reportRecommendationsActionClicked } = useActions(recommendationsLogic)
    if (gap.action === 'manage_source') {
        return (
            <LemonButton
                size="xsmall"
                type="secondary"
                to={urls.dataWarehouseSource(`managed-${gap.sourceId}`)}
                data-attr="marketing-recommendations-data-gap-manage-source"
                onClick={() => reportRecommendationsActionClicked('manage_source', location)}
            >
                Manage source
            </LemonButton>
        )
    }
    const { action } = gap
    if (!action) {
        return null
    }
    const dataAttr = `marketing-recommendations-data-gap-${action.replaceAll('_', '-')}`
    // Without Setup, conversion goals live on the settings page rather than in a tab of this scene.
    return action === 'edit_conversion_goals' && !setupEnabled ? (
        <LemonButton
            size="xsmall"
            type="secondary"
            to={urls.settings('environment-marketing-analytics', 'marketing-settings')}
            data-attr={dataAttr}
            onClick={() => reportRecommendationsActionClicked(action, location)}
        >
            {NAVIGATION_LABELS[action]}
        </LemonButton>
    ) : (
        <LemonButton
            size="xsmall"
            type="secondary"
            data-attr={dataAttr}
            onClick={() => openDataGapTarget(action, location)}
        >
            {NAVIGATION_LABELS[action]}
        </LemonButton>
    )
}

export function RecommendationServerDataGap({
    gap,
    location,
}: {
    gap: ServerDataGap
    location: RecommendationsActionLocation
}): JSX.Element {
    return (
        <div className="flex items-start justify-between gap-3 rounded border px-3 py-2">
            <div className="flex min-w-0 flex-col gap-0.5">
                {gap.sourceName && <span className="font-semibold">{gap.sourceName}</span>}
                <p className="mb-0 text-xs text-secondary">{gap.message}</p>
            </div>
            <GapAction gap={gap} location={location} />
        </div>
    )
}
