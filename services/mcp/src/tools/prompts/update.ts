import type { z } from 'zod'

import { PromptUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { promptFetch } from './api'

const schema = PromptUpdateSchema

type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema>['handler'] = async (context: Context, { name, prompt }: Params) => {
    const existing = await promptFetch<{ id: number }>(context, `/name/${name}/`)
    return promptFetch(context, `/${existing.id}/`, {
        method: 'PATCH',
        body: { prompt },
    })
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'prompt-update',
    schema,
    handler: updateHandler,
})

export default tool
