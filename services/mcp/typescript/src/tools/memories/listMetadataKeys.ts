import type { z } from 'zod'

import { MemoryListMetadataKeysSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = MemoryListMetadataKeysSchema
type Params = z.infer<typeof schema>

export const listMetadataKeysHandler: ToolBase<typeof schema>['handler'] = async (context: Context, _params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.memories({ projectId }).listMetadataKeys()

    if (!result.success) {
        throw new Error(`Failed to list metadata keys: ${result.error.message}`)
    }

    const { keys } = result.data

    if (keys.length === 0) {
        return {
            message: 'No metadata keys found in any memories.',
            keys: [],
        }
    }

    return {
        message: `Available metadata keys across all memories: ${keys.join(', ')}`,
        keys,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'memory-list-metadata-keys',
    schema,
    handler: listMetadataKeysHandler,
})

export default tool
