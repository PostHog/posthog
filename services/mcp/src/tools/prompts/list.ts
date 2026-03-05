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

    interface PromptSummary {
        id: number
        name: string
        version: number
        latest_version: number
        version_count: number
        created_at: string
        updated_at: string
    }

    const result = await promptFetch<{ results: PromptSummary[] }>(context, '/', { query })

    return (result.results ?? []).map((p) => ({
        id: p.id,
        name: p.name,
        version: p.version,
        latest_version: p.latest_version,
        version_count: p.version_count,
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
