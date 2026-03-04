import type { z } from 'zod'

import { FeatureFlagGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

type TResult = Array<{ id: number; key: string; name: string; active: boolean; updated_at?: string | null }>

const schema = FeatureFlagGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler: ToolBase<typeof schema, TResult>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const flagsResult = await context.api.featureFlags({ projectId }).list({
        params: {
            limit: params.data?.limit,
            offset: params.data?.offset,
        },
    })

    if (!flagsResult.success) {
        throw new Error(`Failed to get feature flags: ${flagsResult.error.message}`)
    }

    return flagsResult.data
}

const tool = (): ToolBase<typeof schema, TResult> => ({
    name: 'feature-flag-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
