import { MakeLogicType, actions, kea, key, listeners, path, props, reducers } from 'kea'

import { LemonDialog } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import {
    MarketingAnalyticsTab,
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

export type DashboardSetupPromptKind = 'sources' | 'conversion-goals'

interface DashboardSetupPromptsProps {
    projectId: number
    userId?: string
}

export const dashboardSetupPromptsLogic = kea<
    MakeLogicType<
        { dismissed: Record<DashboardSetupPromptKind, boolean> },
        {
            dismiss: (kind: DashboardSetupPromptKind) => { kind: DashboardSetupPromptKind }
            restore: (kind: DashboardSetupPromptKind) => { kind: DashboardSetupPromptKind }
            openSetup: (kind: DashboardSetupPromptKind) => { kind: DashboardSetupPromptKind }
        },
        DashboardSetupPromptsProps
    >
>([
    props({} as DashboardSetupPromptsProps),
    key(({ projectId, userId }) => `${userId}:${projectId}`),
    path((key) => ['products', 'marketing_analytics', 'setup', 'dashboardSetupPromptsLogic', key]),
    actions({
        dismiss: (kind: DashboardSetupPromptKind) => ({ kind }),
        restore: (kind: DashboardSetupPromptKind) => ({ kind }),
        openSetup: (kind: DashboardSetupPromptKind) => ({ kind }),
    }),
    reducers(({ props }) => ({
        dismissed: [
            { sources: false, 'conversion-goals': false },
            { persist: true, prefix: `${props.userId}:${props.projectId}__` },
            {
                dismiss: (state, { kind }) => ({ ...state, [kind]: true }),
                restore: (state, { kind }) => ({ ...state, [kind]: false }),
            },
        ],
    })),
    listeners(({ actions, props }) => ({
        dismiss: ({ kind }) => {
            LemonDialog.open({
                title: kind === 'sources' ? 'Source suggestions hidden' : 'Conversion recommendations hidden',
                content:
                    kind === 'sources'
                        ? 'You can review your sources and show these suggestions again in Setup → Ad platforms & sources.'
                        : 'You can review your recommendations and show them again in Setup → Conversion goals.',
                primaryButton: { children: 'Got it' },
                secondaryButton: { children: 'Open Setup', onClick: () => actions.openSetup(kind) },
            })
        },
        openSetup: ({ kind }) => {
            if (teamLogic.values.currentTeamId === props.projectId) {
                marketingAnalyticsLogic.actions.setSetupSection(
                    kind === 'sources' ? SetupSection.SOURCES : SetupSection.CONVERSION_GOALS
                )
                marketingAnalyticsLogic.actions.setActiveTab(MarketingAnalyticsTab.SETUP)
            }
        },
    })),
])
