import { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import type { Context, ToolBase } from '@/tools/types'

const LabelSchema = z
    .string()
    .min(1)
    .max(60)
    .describe('Button text. Short and in sentence case, naming what the button does.')

const ComposeActionSchema = z.object({
    kind: z.literal('compose'),
    label: LabelSchema,
    prompt: z
        .string()
        .min(1)
        .describe(
            'Text to prefill the new-task composer with. The user reads it and sends it themselves, so nothing runs on click.'
        ),
    repo: z
        .string()
        .optional()
        .describe('Repository slug to preselect, e.g. `posthog/posthog`. Omit when the task has no repository.'),
})

const OpenSpaceActionSchema = z.object({
    kind: z.literal('open_space'),
    label: LabelSchema,
    channel_id: z.string().min(1).describe('Id of the channel whose feed to open. Resolve it with channel-list.'),
})

const OpenCanvasActionSchema = z.object({
    kind: z.literal('open_canvas'),
    label: LabelSchema,
    channel_id: z.string().min(1).describe('Id of the channel the canvas lives in. Required.'),
    canvas_id: z.string().min(1).describe('Id of the canvas to open. Required.'),
})

// There is deliberately no URL parameter: this tool is called by agents whose context can
// contain untrusted text, and an arbitrary URL the user is invited to click is a phishing
// primitive.
const schema = z.object({
    actions: z
        .array(z.discriminatedUnion('kind', [ComposeActionSchema, OpenSpaceActionSchema, OpenCanvasActionSchema]))
        .min(1)
        .max(4)
        .describe('One to four actions, in the order they should appear.'),
})

type Params = z.infer<typeof schema>

export const taskShowActionsHandler: ToolBase<typeof schema, Params>['handler'] = async (
    _context: Context,
    params: Params
) => params

export default (): ToolBase<typeof schema, Params> =>
    withUiApp('task-show-actions', {
        name: 'task-show-actions',
        schema,
        handler: taskShowActionsHandler,
    })
