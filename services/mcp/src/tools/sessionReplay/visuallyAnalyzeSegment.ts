import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

import { invokeMcpTool } from '../posthogAiTools/invokeTool'

const schema = z.object({
    session_id: z.string().min(1).describe('The session recording ID to analyze.'),
    start_timestamp: z
        .string()
        .regex(/^\d{1,2}:\d{2}:\d{2}$/, 'Must be in hh:mm:ss format')
        .describe("Start timestamp within the session in hh:mm:ss format (e.g. '00:01:30')."),
    end_timestamp: z
        .string()
        .regex(/^\d{1,2}:\d{2}:\d{2}$/, 'Must be in hh:mm:ss format')
        .describe("End timestamp within the session in hh:mm:ss format (e.g. '00:03:00')."),
    angle: z
        .string()
        .min(1)
        .describe(
            'What to pay attention to when analyzing the video segment. ' +
                "For example: 'focus on user confusion around the checkout flow' or 'look for UI rendering issues'."
        ),
})

type Params = z.infer<typeof schema>

const handler: ToolBase<typeof schema, string>['handler'] = async (context: Context, params: Params) => {
    const result = await invokeMcpTool(context, 'visually_analyze_segment_of_session_recording', {
        session_id: params.session_id,
        start_timestamp: params.start_timestamp,
        end_timestamp: params.end_timestamp,
        angle: params.angle,
    })

    if (!result.success) {
        throw new Error(result.content)
    }

    return result.content
}

const tool = (): ToolBase<typeof schema, string> => ({
    name: 'visually-analyze-session-segment',
    schema,
    handler,
})

export default tool
