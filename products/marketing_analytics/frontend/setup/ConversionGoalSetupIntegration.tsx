import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import {
    MarketingAnalyticsTab,
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'
import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { conversionGoalDraftLogic, previewRequestFromTool } from './conversionGoalDraftLogic'
import { conversionRecommendationsLogic } from './conversionRecommendationsLogic'

const CONTEXT: AttachedContextItem[] = [
    {
        type: 'skill',
        key: 'setting-up-marketing-conversions',
        label: 'Marketing conversion setup',
        dismissGroup: 'marketing-conversion-setup',
    },
    {
        type: 'instructions',
        hidden: true,
        dismissGroup: 'marketing-conversion-setup',
        value:
            'The user is reviewing Marketing analytics conversion goals. Load the setting-up-marketing-conversions skill. ' +
            'Read marketing-analytics-conversion-recommendations, marketing-analytics-setup-plan, and marketing-analytics-conversion-goals for this project. ' +
            'Recommendations are read-only. Preserve the business outcome and counting entity. Report unsupported definitions ' +
            'and missing evidence instead of replacing them with another metric. Use marketing-analytics-preview-conversion-goal ' +
            'only for supported drafts. Its latest completed call offers a draft for review on this page; it does not save a goal. ' +
            'The user can edit, preview, and save it in the page. Do not save it unless the user separately requests a write.',
    },
]

export function ConversionGoalSetupIntegration(): null {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { loadCurrentTeam } = useActions(teamLogic)
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)
    const { activeTab, setupSection } = useValues(marketingAnalyticsLogic)
    const { loadMarketingAnalyticsConfig } = useActions(marketingAnalyticsSettingsLogic)
    const { loadSetupPlan } = useActions(setupPlanLogic)
    const logic = useMountedLogic(conversionGoalDraftLogic({ projectId: currentTeamId ?? -1 }))
    const { receiveDraft } = useActions(logic)
    useMountedLogic(
        conversionRecommendationsLogic({
            projectId: currentTeamId ?? -1,
            enabled: sceneIntegrationEnabled,
            userId: user?.uuid,
        })
    )
    const active = sceneIntegrationEnabled && currentTeamId !== null
    const contextItems = useMemo<AttachedContextItem[]>(
        () => [
            ...CONTEXT,
            {
                type: 'marketing_setup_project',
                key: currentTeamId ?? 'unloaded',
                value: JSON.stringify({ project_id: currentTeamId }),
                hidden: true,
                dismissGroup: 'marketing-conversion-setup',
            },
        ],
        [currentTeamId]
    )

    useSceneAgentPanel({
        sceneKey: 'marketing-conversion-setup',
        contextItems,
        active:
            active &&
            activeTab === MarketingAnalyticsTab.SETUP &&
            (setupSection === SetupSection.SUGGESTIONS || setupSection === SetupSection.CONVERSION_GOALS),
        autoOpen: false,
        headlines: ['Which outcomes should your marketing measure?'],
    })
    useMcpToolApplyBack({
        tools: ['marketing-analytics-preview-conversion-goal'],
        targetKey: `marketing-conversion-setup:${currentTeamId ?? 'unloaded'}`,
        active,
        applyOn: 'turn_end',
        onApply: (_event, { innerInput }) => {
            if (innerInput?.project_id != null && String(innerInput.project_id) !== String(currentTeamId)) {
                return
            }
            const request = previewRequestFromTool(innerInput)
            if (request) {
                receiveDraft(request)
            }
        },
    })
    useMcpToolApplyBack({
        tools: [
            'marketing-analytics-apply-conversion-goal',
            'marketing-analytics-create-conversion-goal',
            'marketing-analytics-update-conversion-goal',
            'marketing-analytics-delete-conversion-goal',
        ],
        targetKey: `marketing-conversion-goals:${currentTeamId ?? 'unloaded'}`,
        active,
        onApply: (_event, { innerInput }) => {
            if (innerInput?.project_id != null && String(innerInput.project_id) !== String(currentTeamId)) {
                return
            }
            loadCurrentTeam()
            loadMarketingAnalyticsConfig()
            loadSetupPlan({ refresh: true })
        },
    })
    return null
}
