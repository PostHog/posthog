import posthog from 'posthog-js'

import { AgentPromptDestination } from 'lib/components/AgentPromptButton/AgentPromptButton'

import { getServiceName } from 'products/logs/frontend/components/LogsViewer/LogContextSelector/logContextUtils'
import { ParsedLogMessage } from 'products/logs/frontend/types'

import type { LogContextLinksSurface } from './LogContextLinks'
import { MissingLink } from './missingLinkPrompt'

export type InvestigateOption = AgentPromptDestination | 'posthog-ai-task'

export type InvestigateRoute = 'side-panel-task' | 'side-panel-already-launching' | 'legacy-ask' | 'ai-scene'

export interface MissingLinkEventContext {
    missing: MissingLink[]
    source: `log-${LogContextLinksSurface}`
    service_name: string | null
}

export function missingLinkEventContext(
    log: ParsedLogMessage,
    missing: MissingLink[],
    surface: LogContextLinksSurface
): MissingLinkEventContext {
    return { missing, source: `log-${surface}`, service_name: getServiceName(log) }
}

// pinned: analytics event names and properties, renaming breaks dashboards
export function captureInvestigate(
    event: 'shown' | 'clicked',
    context: MissingLinkEventContext,
    extra: { option?: InvestigateOption; route?: InvestigateRoute } = {}
): void {
    posthog.capture(`logs missing link investigate ${event}`, { ...context, ...extra })
}

// pinned: analytics event name and properties. `task_id` joins this event to the PostHog AI
// `task_run_started` and `task_run_terminated` events, which show whether the task ran and finished.
export function captureInvestigateTaskCreated(
    context: MissingLinkEventContext,
    task: { task_id: string; run_id?: string; auto_submitted: boolean }
): void {
    posthog.capture('logs missing link investigate task created', { ...context, ...task })
}
