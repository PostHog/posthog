import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import posthog from 'lib/posthog-typed'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ProductKey } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import type { HarnessRow, KPIData, ToolRow } from '../mcpDashboardOverviewLogic'
import { mcpDashboardOverviewLogic } from '../mcpDashboardOverviewLogic'
import { buildChips, buildEditorPrompt, buildHeadline, buildMaxPrompt, type FirstLookChip } from './firstLookCopy'
import type { mcpFirstLookLogicType } from './mcpFirstLookLogicType'

export const mcpFirstLookLogic = kea<mcpFirstLookLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'firstLook', 'mcpFirstLookLogic']),
    connect(() => ({
        values: [
            mcpDashboardOverviewLogic,
            ['kpis', 'toolRows', 'harnessRows'],
            mcpAnalyticsOnboardingLogic,
            ['isOnboarded'],
            userLogic,
            ['user'],
            teamLogic,
            ['currentTeam'],
            organizationLogic,
            ['currentOrganization'],
        ],
        actions: [userLogic, ['updateHasSeenProductIntroFor']],
    })),
    actions({
        dismiss: true,
        askMax: true,
        dismissAndAskMax: true,
        toggleEditor: true,
    }),
    reducers({
        // Secondary path; collapsed by default to keep the hero tight.
        editorExpanded: [false, { toggleEditor: (state) => !state }],
    }),
    selectors({
        // Once per user, never on demo, and only after data loads (avoids an empty-flash).
        shouldShow: [
            (s) => [s.isOnboarded, s.user, s.currentTeam, s.kpis, s.toolRows],
            (isOnboarded, user, currentTeam, kpis: KPIData, toolRows: ToolRow[]): boolean => {
                const hasData = toolRows.length > 0 || kpis.toolCalls.value > 0
                return (
                    Boolean(isOnboarded) &&
                    hasData &&
                    !user?.has_seen_product_intro_for?.[ProductKey.MCP_ANALYTICS] &&
                    !currentTeam?.is_demo
                )
            },
        ],
        topTool: [(s) => [s.toolRows], (toolRows: ToolRow[]): ToolRow | null => toolRows[0] ?? null],
        worstErrorTool: [
            (s) => [s.toolRows],
            (toolRows: ToolRow[]): ToolRow | null =>
                toolRows.length ? [...toolRows].sort((a, b) => b.error_rate_pct - a.error_rate_pct)[0] : null,
        ],
        dominantClient: [
            (s) => [s.harnessRows],
            (harnessRows: HarnessRow[]): string | null => harnessRows[0]?.category ?? null,
        ],
        headline: [
            (s) => [s.currentOrganization, s.currentTeam, s.topTool, s.dominantClient, s.kpis],
            (currentOrganization, currentTeam, topTool, dominantClient, kpis: KPIData): string =>
                buildHeadline({
                    company: currentOrganization?.name,
                    project: currentTeam?.name,
                    topTool,
                    client: dominantClient,
                    kpis,
                }),
        ],
        maxPrompt: [
            (s) => [s.worstErrorTool, s.topTool],
            (worstErrorTool, topTool): string => buildMaxPrompt({ worstErrorTool, topTool }),
        ],
        editorPrompt: [
            (s) => [s.dominantClient],
            (dominantClient): { label: string; prompt: string } => buildEditorPrompt({ client: dominantClient }),
        ],
        chips: [
            (s) => [s.topTool, s.worstErrorTool, s.kpis, s.dominantClient],
            (topTool, worstErrorTool, kpis: KPIData, dominantClient): FirstLookChip[] =>
                buildChips({ topTool, worstErrorTool, kpis, client: dominantClient }),
        ],
        eventProperties: [
            (s) => [s.dominantClient, s.topTool, s.worstErrorTool],
            (dominantClient, topTool: ToolRow | null, worstErrorTool: ToolRow | null): Record<string, unknown> => ({
                client: dominantClient,
                busiest_tool: topTool?.tool ?? null,
                flakiest_tool: worstErrorTool?.tool ?? null,
            }),
        ],
    }),
    listeners(({ values, actions }) => ({
        dismiss: () => {
            posthog.captureRaw('mcp analytics first look dismissed', values.eventProperties)
            actions.updateHasSeenProductIntroFor(ProductKey.MCP_ANALYTICS)
        },
        askMax: () => {
            posthog.captureRaw('mcp analytics first look ask ai clicked', values.eventProperties)
            // Prefill, don't auto-submit: the prompt embeds tool names from `$mcp_tool_call`
            // events, which anyone with the project token can set — auto-running it would let a
            // seeded tool name reach PostHog AI as an instruction. The user reviews, then sends.
            sidePanelStateLogic.findMounted()?.actions.openSidePanel(SidePanelTab.Max, values.maxPrompt)
        },
        dismissAndAskMax: () => {
            actions.askMax()
            actions.dismiss()
        },
        toggleEditor: () => {
            // Capture the expand only, not the collapse.
            if (values.editorExpanded) {
                posthog.captureRaw('mcp analytics first look editor expanded', values.eventProperties)
            }
        },
    })),
])
