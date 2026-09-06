import type { z } from 'zod'

import { AnalyticsEvent } from '@/lib/posthog/analytics'
import { MissingCapabilityReportSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = MissingCapabilityReportSchema

type Params = z.infer<typeof schema>

type Result = {
    received: boolean
    message: string
}

const RESPONSE_MESSAGE =
    'Thank you — the gap is recorded on the missing capabilities feed and will be reviewed by the PostHog team. ' +
    "Reporting a gap does not mean your work is done: keep going and finish the user's task with the tools you do have."

export const reportMissingCapabilityHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    // The report is the event: the missing-capabilities feed reads its text from
    // `$mcp_intent`, so the description must ride on that property and no other.
    try {
        await context.trackEvent(AnalyticsEvent.MCP_MISSING_CAPABILITY, {
            $mcp_intent: params.description,
        })
    } catch {
        // Analytics is non-fatal — never surface as a tool failure.
    }

    return {
        received: true,
        message: RESPONSE_MESSAGE,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'report-missing-capability',
    schema,
    handler: reportMissingCapabilityHandler,
})

export default tool
