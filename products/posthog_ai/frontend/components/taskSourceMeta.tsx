import {
    IconBrain,
    IconBug,
    IconDecisionTree,
    IconFlask,
    IconGridMasonry,
    IconHandwave,
    IconHeadset,
    IconMCP,
    IconRefresh,
    IconRewindPlay,
    IconSearch,
    IconSignal,
    IconSparkles,
    IconSupport,
    IconTelescope,
    IconTestTube,
} from '@posthog/icons'

import { IconSlack } from 'lib/lemon-ui/icons'

import { TaskOriginProductEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { TaskRunEnvironment } from '../types/taskTypes'

export type OriginProductMeta = { icon: JSX.Element; label: string }

// Keep the origins and labels in sync with ORIGIN_PRODUCT_META in
// products/desktop/packages/ui/src/features/sidebar/components/items/TaskIcon.tsx, so a task shows the
// same source in the web app and the desktop app. `user_created` and the internal pipelines are absent on
// purpose, so those tasks keep the cloud or laptop icon.
const ORIGIN_PRODUCT_META: Partial<Record<TaskOriginProductEnumApi, OriginProductMeta>> = {
    [TaskOriginProductEnumApi.Slack]: { icon: <IconSlack />, label: 'Slack' },
    [TaskOriginProductEnumApi.SignalReport]: { icon: <IconSignal />, label: 'Signals' },
    [TaskOriginProductEnumApi.SignalsScout]: { icon: <IconTelescope />, label: 'Signals scout' },
    [TaskOriginProductEnumApi.SupportQueue]: { icon: <IconSupport />, label: 'Support' },
    [TaskOriginProductEnumApi.SessionSummaries]: { icon: <IconRewindPlay />, label: 'Session summary' },
    [TaskOriginProductEnumApi.ErrorTracking]: { icon: <IconBug />, label: 'Error tracking' },
    [TaskOriginProductEnumApi.EvalClusters]: { icon: <IconFlask />, label: 'Evals' },
    [TaskOriginProductEnumApi.TaskAnalysis]: { icon: <IconSearch />, label: 'Task analysis' },
    [TaskOriginProductEnumApi.PosthogAi]: { icon: <IconSparkles />, label: 'PostHog AI' },
    [TaskOriginProductEnumApi.Experiments]: { icon: <IconTestTube />, label: 'Experiments' },
    [TaskOriginProductEnumApi.Onboarding]: { icon: <IconHandwave />, label: 'Onboarding' },
    [TaskOriginProductEnumApi.Hogdesk]: { icon: <IconHeadset />, label: 'HogDesk' },
    [TaskOriginProductEnumApi.Loop]: { icon: <IconRefresh />, label: 'Loops' },
    [TaskOriginProductEnumApi.Workflow]: { icon: <IconDecisionTree />, label: 'Workflows' },
    [TaskOriginProductEnumApi.McpAnalytics]: { icon: <IconMCP />, label: 'MCP analytics' },
    [TaskOriginProductEnumApi.SpaceSetup]: { icon: <IconGridMasonry />, label: 'Space setup' },
    [TaskOriginProductEnumApi.Autoresearch]: { icon: <IconBrain />, label: 'Autoresearch' },
}

export function getOriginProductMeta(originProduct?: string): OriginProductMeta | undefined {
    return originProduct ? ORIGIN_PRODUCT_META[originProduct as TaskOriginProductEnumApi] : undefined
}

export function getTaskSourceTooltip(originProduct?: string, environment?: TaskRunEnvironment): string {
    const environmentLabel = !environment
        ? 'Task'
        : environment === TaskRunEnvironment.CLOUD
          ? 'Cloud task'
          : 'Local task'
    const sourceLabel = getOriginProductMeta(originProduct)?.label
    return sourceLabel ? `From ${sourceLabel} · ${environmentLabel}` : environmentLabel
}
