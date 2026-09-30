import type { z } from 'zod'

import { AnalyticsEvent } from '@/lib/posthog/analytics'
import { FEEDBACK_PRODUCT_AREAS, FeedbackSubmitSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = FeedbackSubmitSchema

type Params = z.infer<typeof schema>

type Result = {
    received: boolean
    summary: string
    feedback_type: Params['feedback_type']
    sentiment: Params['sentiment']
    message: string
}

const RESPONSE_MESSAGE =
    'Thank you for the feedback — it has been recorded and will be reviewed by the PostHog team. ' +
    "Submitting feedback does not mean your work is done: keep going and finish the user's task " +
    'using the other available tools.'

const PRODUCT_AREA_NUDGE = ` Next time, set \`product_area\` to one of: ${FEEDBACK_PRODUCT_AREAS.join(', ')}.`

type FeedbackProductArea = (typeof FEEDBACK_PRODUCT_AREAS)[number]

const PRODUCT_AREA_ALIASES = new Map<string, FeedbackProductArea>(
    Object.entries({
        insights: 'product_analytics',
        dashboards: 'product_analytics',
        trends: 'product_analytics',
        funnels: 'product_analytics',
        retention: 'product_analytics',
        cohorts: 'product_analytics',
        persons: 'product_analytics',
        alerts: 'product_analytics',
        subscriptions: 'product_analytics',
        replay: 'session_replay',
        replay_vision: 'session_replay',
        flags: 'feature_flags',
        sql: 'data_warehouse',
        hogql: 'data_warehouse',
        data_warehouse_sources: 'data_warehouse',
        cdp_destinations: 'data_pipelines',
        destinations: 'data_pipelines',
        batch_exports: 'data_pipelines',
        ai_observability: 'llm_analytics',
        llm_observability: 'llm_analytics',
        signals: 'posthog_ai',
        inbox: 'posthog_ai',
        self_driving: 'posthog_ai',
    })
)

const isKnownProductArea = (value: string | undefined): value is FeedbackProductArea =>
    (FEEDBACK_PRODUCT_AREAS as readonly (string | undefined)[]).includes(value)

const toKey = (value: string): string =>
    value
        .trim()
        .toLowerCase()
        .replace(/[\s-]+/g, '_')

// Agents often send compound areas like "session replay / replay vision"; the first part names the product.
const normalizeProductArea = (value: string | undefined): string | undefined => {
    if (!value?.trim()) {
        return undefined
    }
    const key = toKey(value)
    for (const candidate of [key, toKey(value.split('/')[0] ?? value)]) {
        if (isKnownProductArea(candidate)) {
            return candidate
        }
        const alias = PRODUCT_AREA_ALIASES.get(candidate)
        if (alias) {
            return alias
        }
    }
    return key
}

export const submitFeedbackHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const productArea = normalizeProductArea(params.product_area)
    // `context.trackEvent` is itself best-effort (the MCP-class implementation wraps
    // analytics in its own try/catch). The outer try/catch here defends against any
    // unexpected throw on the way *to* trackEvent (e.g. a future refactor) so the
    // agent never sees this tool fail because of an analytics issue.
    try {
        await context.trackEvent(AnalyticsEvent.MCP_FEEDBACK_SUBMITTED, {
            feedback_summary: params.summary,
            feedback_type: params.feedback_type,
            feedback_sentiment: params.sentiment,
            feedback_product_area: productArea,
            feedback_category: params.category,
            feedback_scout_skill_name: params.scout_skill_name,
            feedback_scout_skill_version: params.scout_skill_version,
            feedback_scout_category: params.scout_category,
            feedback_task_completed: params.task_completed,
            feedback_tools_used: params.tools_used,
            feedback_friction_points: params.friction_points,
            feedback_suggested_improvement: params.suggested_improvement,
            feedback_user_request: params.user_request,
            feedback_details: params.details,
        })
    } catch {
        // Analytics is non-fatal — never surface as a tool failure.
    }

    return {
        received: true,
        summary: params.summary,
        feedback_type: params.feedback_type,
        sentiment: params.sentiment,
        message: isKnownProductArea(productArea) ? RESPONSE_MESSAGE : RESPONSE_MESSAGE + PRODUCT_AREA_NUDGE,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'agent-feedback',
    schema,
    handler: submitFeedbackHandler,
})

export default tool
