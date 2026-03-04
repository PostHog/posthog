import type { z } from 'zod'

import { PromptListSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { promptFetch } from './api'

const schema = PromptListSchema

type Params = z.infer<typeof schema>

export const listHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const query: Record<string, string> = {}
    if (params.search) {
        query.search = params.search
    }

    const result = await promptFetch<{ results: any[] }>(context, '/', { query })

    return (result.results ?? result).map((p: any) => ({
        id: p.id,
        name: p.name,
        version: p.version,
        created_at: p.created_at,
        updated_at: p.updated_at,
    }))
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'prompt-list',
    schema,
    handler: listHandler,
})

export default tool
