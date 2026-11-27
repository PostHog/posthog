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

export interface ServerDataGapAction {
    label: string
    dataAttr: string
    to?: string
    onClick: () => void
}

export function useServerDataGapAction(
    gap: ServerDataGap,
    location: RecommendationsActionLocation
): ServerDataGapAction | null {
    const { setupEnabled } = useValues(recommendationsLogic)
    const { openDataGapTarget, reportRecommendationsActionClicked } = useActions(recommendationsLogic)
    if (gap.action === 'manage_source') {
        return {
            label: 'Manage source',
            dataAttr: 'marketing-recommendations-data-gap-manage-source',
            to: urls.dataWarehouseSource(`managed-${gap.sourceId}`),
            onClick: () => reportRecommendationsActionClicked('manage_source', location),
        }
    }
    const { action } = gap
    if (!action) {
        return null
    }
    const label = NAVIGATION_LABELS[action]
    const dataAttr = `marketing-recommendations-data-gap-${action.replaceAll('_', '-')}`
    // Without Setup, conversion goals live on the settings page rather than in a tab of this scene.
    return action === 'edit_conversion_goals' && !setupEnabled
        ? {
              label,
              dataAttr,
              to: urls.settings('environment-marketing-analytics', 'marketing-settings'),
              onClick: () => reportRecommendationsActionClicked(action, location),
          }
        : { label, dataAttr, onClick: () => openDataGapTarget(action, location) }
}

function GapAction({
    gap,
    location,
}: {
    gap: ServerDataGap
    location: RecommendationsActionLocation
}): JSX.Element | null {
    const action = useServerDataGapAction(gap, location)
    if (!action) {
        return null
    }
    return (
        <LemonButton size="xsmall" type="secondary" to={action.to} data-attr={action.dataAttr} onClick={action.onClick}>
            {action.label}
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
