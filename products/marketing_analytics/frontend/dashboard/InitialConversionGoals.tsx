import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight, IconTarget } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonModal } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'
import { ConversionGoalDetails } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/common/ConversionGoalDetails'
import { ConversionGoalsConfiguration } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/ConversionGoalsConfiguration'
import {
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'

import { initialConversionGoalsLogic } from './initialConversionGoalsLogic'

export function InitialConversionGoals({ showEmptyState = true }: { showEmptyState?: boolean }): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const logic = initialConversionGoalsLogic({
        teamId: currentTeamId ?? 0,
        canInitialize: !!currentTeamId && !restrictedReason,
    })
    const { goals, loading, error, initialized, dismissed, dismissedGoalIds } = useValues(logic)
    const { load, dismiss, expand, dismissGoal } = useActions(logic)
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const { openSetup } = useActions(marketingAnalyticsLogic)
    const [editingGoalId, setEditingGoalId] = useState<string | null>(null)
    const visibleGoals = goals
        .filter((goal) => !dismissedGoalIds.includes(goal.conversion_goal_id))
        .map(
            (goal) => conversion_goals.find((current) => current.conversion_goal_id === goal.conversion_goal_id) ?? goal
        )

    if (goals.length > 0 && !visibleGoals.length) {
        return null
    }
    if (restrictedReason) {
        return conversion_goals.length ? null : (
            <LemonBanner type="info">Ask a project admin to set up conversion goals.</LemonBanner>
        )
    }
    if (error) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: load }}>
                {error}
            </LemonBanner>
        )
    }
    if (loading && !goals.length) {
        return conversion_goals.length ? null : (
            <LemonBanner type="info">Checking your events for initial conversion goals…</LemonBanner>
        )
    }
    if (!goals.length) {
        return initialized || !showEmptyState ? null : (
            <LemonCard hoverEffect={false} className="p-4">
                <div className="flex flex-wrap items-center justify-between gap-4">
                    <div className="flex items-start gap-3">
                        <IconTarget className="text-2xl shrink-0 text-secondary" />
                        <div>
                            <h3 className="mb-1">Choose what counts as a conversion</h3>
                            <p className="text-secondary mb-0">
                                We will suggest goals as events arrive. You can also create your first goal in Setup.
                            </p>
                        </div>
                    </div>
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            openSetup(SetupSection.CONVERSION_GOALS, 'dashboard_goal_suggestions')
                        }}
                    >
                        Set up conversion goals
                    </LemonButton>
                </div>
            </LemonCard>
        )
    }
    return (
        <LemonCard hoverEffect={false} className="p-3">
            <LemonButton fullWidth noPadding aria-expanded={!dismissed} onClick={dismissed ? expand : dismiss}>
                <span className="flex w-full items-center justify-between gap-3 py-1 text-left whitespace-normal">
                    <span className="flex items-center gap-2 font-semibold text-sm">
                        <span className="flex shrink-0 text-base" aria-hidden="true">
                            {dismissed ? <IconChevronRight /> : <IconChevronDown />}
                        </span>
                        <span>We created these conversion goals ({visibleGoals.length})</span>
                    </span>
                </span>
            </LemonButton>
            {!dismissed && (
                <>
                    <p className="text-secondary">
                        Based on your recent events. Review what counts as a conversion for your business. You can
                        manage these goals later in Setup or Settings → Marketing analytics.
                    </p>
                    {visibleGoals.map((goal) => (
                        <div
                            key={goal.conversion_goal_id}
                            className="flex flex-wrap items-center justify-between gap-3 py-2 border-t"
                        >
                            <div>
                                <span>{goal.conversion_goal_name}</span>
                                <ConversionGoalDetails goal={goal} />
                            </div>
                            <div className="flex gap-2">
                                <LemonButton size="small" onClick={() => setEditingGoalId(goal.conversion_goal_id)}>
                                    View
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    tooltip="Hide this notice. The goal remains available in Setup."
                                    onClick={() => dismissGoal(goal.conversion_goal_id)}
                                >
                                    Dismiss
                                </LemonButton>
                            </div>
                        </div>
                    ))}
                </>
            )}
            <LemonButton
                type="tertiary"
                onClick={() => {
                    openSetup(SetupSection.CONVERSION_GOALS, 'dashboard_goal_suggestions')
                }}
            >
                Review in Setup
            </LemonButton>
            {editingGoalId && (
                <LemonModal
                    isOpen
                    onClose={() => {
                        setEditingGoalId(null)
                        load()
                    }}
                    title="Conversion goal details"
                    width={900}
                >
                    <ConversionGoalsConfiguration initialEditingGoalId={editingGoalId} hideTitle hideDescription />
                </LemonModal>
            )}
        </LemonCard>
    )
}
