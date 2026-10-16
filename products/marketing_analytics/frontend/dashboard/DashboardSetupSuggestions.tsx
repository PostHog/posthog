import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { suggestionsForSection } from 'scenes/marketing-analytics/Setup/sectionRouting'
import { SuggestionRow } from 'scenes/marketing-analytics/Setup/SuggestionRow'
import {
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

export function DashboardSetupSuggestions(): JSX.Element {
    const { setupPlan, setupPlanLoading, visibleSuggestions } = useValues(setupPlanLogic)
    const { loadSetupPlan, reviewSuggestion } = useActions(setupPlanLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { dashboardView } = useValues(marketingAnalyticsLogic)
    const { openSetup, reportDashboardControlUsed } = useActions(marketingAnalyticsLogic)
    const [sourcesExpanded, setSourcesExpanded] = useLocalStorage('marketing-source-suggestions-expanded', false)
    const [goalsExpanded, setGoalsExpanded] = useLocalStorage('marketing-goal-suggestions-expanded', false)
    const requestedSetupPlan = useRef(false)
    useEffect(() => {
        if (!setupPlan && !setupPlanLoading && !requestedSetupPlan.current) {
            requestedSetupPlan.current = true
            loadSetupPlan()
        }
    }, [setupPlan, setupPlanLoading, loadSetupPlan])
    const groups = [
        {
            key: 'sources',
            label: 'Suggested ad sources',
            section: SetupSection.SOURCES,
            entryPoint: 'dashboard_source_suggestions' as const,
            suggestions: featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]
                ? []
                : visibleSuggestions.filter((suggestion) => suggestion.kind === 'connect_source'),
            expanded: sourcesExpanded,
            setExpanded: setSourcesExpanded,
        },
        {
            key: 'goals',
            label: 'Suggested conversion goals',
            section: SetupSection.CONVERSION_GOALS,
            entryPoint: 'dashboard_goal_suggestions' as const,
            suggestions: suggestionsForSection(visibleSuggestions, SetupSection.CONVERSION_GOALS),
            expanded: goalsExpanded,
            setExpanded: setGoalsExpanded,
        },
    ]
    return (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,24rem),1fr))] items-start gap-2 empty:hidden">
            {groups
                .filter((group) => group.suggestions.length > 0)
                .map((group) => (
                    <div key={group.key} className="border rounded relative">
                        <LemonButton
                            className="absolute right-2 top-0 z-10"
                            size="small"
                            onClick={() => openSetup(group.section, group.entryPoint)}
                        >
                            Review in Setup
                        </LemonButton>
                        <LemonCollapse
                            embedded
                            size="small"
                            activeKey={group.expanded ? group.key : null}
                            onChange={(key) => {
                                reportDashboardControlUsed(
                                    dashboardView,
                                    `${group.key === 'goals' ? 'goal' : 'source'}_suggestions`,
                                    key !== null
                                )
                                group.setExpanded(key !== null)
                            }}
                            panels={[
                                {
                                    key: group.key,
                                    header: {
                                        children: `${group.label} (${group.suggestions.length})`,
                                        className: 'pr-36',
                                    },
                                    content: group.suggestions.map((suggestion) => (
                                        <SuggestionRow
                                            key={suggestion.id}
                                            suggestion={suggestion}
                                            currentSection={group.section}
                                            onReview={(item) => {
                                                openSetup(group.section, group.entryPoint)
                                                reviewSuggestion(item)
                                            }}
                                        />
                                    )),
                                },
                            ]}
                        />
                    </div>
                ))}
        </div>
    )
}
