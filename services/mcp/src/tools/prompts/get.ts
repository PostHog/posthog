import type { z } from 'zod'

import { PromptGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { promptFetch } from './api'

const schema = PromptGetSchema

type Params = z.infer<typeof schema>

export const getHandler: ToolBase<typeof schema>['handler'] = async (context: Context, { name, version }: Params) => {
    const query: Record<string, string> = {}
    if (version !== undefined) {
        query.version = version.toString()
    }
    return promptFetch(context, `/name/${name}/`, { query })
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'prompt-get',
    schema,
    handler: getHandler,
})

export default tool
