import type { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { FEATURE_FLAG_LIST_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { FeatureFlagGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = FeatureFlagGetAllSchema

type Params = z.infer<typeof schema>
type TResult = {
    count: number
    results: Array<Pick<Schemas.FeatureFlag, 'id' | 'key' | 'name' | 'active' | 'updated_at'>>
    next: string | null
    previous: string | null
    _posthogUrl: string
}

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

    // The API client returns a plain array, but the UI app expects
    // the paginated envelope shape { count, results, next, previous }
    const flags = flagsResult.data
    return {
        count: flags.length,
        results: flags,
        next: null,
        previous: null,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/feature_flags`,
    }
}

const tool = (): ToolBase<typeof schema, TResult> => ({
    name: 'feature-flag-get-all',
    schema,
    handler: getAllHandler,
    _meta: {
        ui: {
            resourceUri: FEATURE_FLAG_LIST_RESOURCE_URI,
        },
    },
})

export default tool
