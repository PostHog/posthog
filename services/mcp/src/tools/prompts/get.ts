import type { z } from 'zod'

import { PromptGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { promptFetch } from './api'

const schema = PromptGetSchema

type Params = z.infer<typeof schema>

export const getHandler: ToolBase<typeof schema>['handler'] = async (context: Context, { name }: Params) => {
    return promptFetch(context, `/name/${name}/`)
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'prompt-get',
    schema,
    handler: getHandler,
})

export default tool
