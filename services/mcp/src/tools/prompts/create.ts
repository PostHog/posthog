import type { z } from 'zod'

import { PromptCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { promptFetch } from './api'

const schema = PromptCreateSchema

type Params = z.infer<typeof schema>

export const createHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    return promptFetch(context, '/', {
        method: 'POST',
        body: { name: params.name, prompt: params.prompt },
    })
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'prompt-create',
    schema,
    handler: createHandler,
})

export default tool
