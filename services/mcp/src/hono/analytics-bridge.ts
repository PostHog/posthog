import { getPostHogClient } from '@/lib/posthog'
import {
    AnalyticsEvent,
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
} from '@/lib/posthog/analytics'
import type { RequestProperties } from '@/lib/request-properties'

import type { ResolvedState } from './request-state-resolver'

export class AnalyticsBridge {
    async trackInitEvent(props: RequestProperties, state: ResolvedState): Promise<void> {
        try {
            const analyticsContext = await state.reqCtx.getAnalyticsContextSafe(state.context)
            const initDurationMs = props.requestStartTime ? Date.now() - props.requestStartTime : undefined

            getPostHogClient().capture({
                distinctId: state.distinctId,
                event: AnalyticsEvent.MCP_INIT,
                properties: {
                    ...state.reqCtx.buildClientProperties(props),
                    tool_count: state.allTools.length,
                    has_organization_id: !!props.organizationId,
                    has_project_id: !!props.projectId,
                    read_only: !!props.readOnly,
                    via_sse_redirect: !!props.viaSseRedirect,
                    ...(props.mode ? { mcp_mode_explicit: props.mode } : {}),
                    ...(initDurationMs !== undefined ? { init_duration_ms: initDurationMs } : {}),
                    ...(props.sessionId
                        ? { $session_id: await state.reqCtx.getSessionUuid(props.sessionId) }
                        : {}),
                    ...(analyticsContext ? buildMCPContextProperties(analyticsContext) : {}),
                },
                ...(analyticsContext ? { groups: buildMCPAnalyticsGroups(analyticsContext) } : {}),
            })
        } catch {
            // skip
        }
    }
}
