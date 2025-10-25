import { ErrorTrackingUpdateIssueSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = ErrorTrackingUpdateIssueSchema

type Params = z.infer<typeof schema>

export const updateIssueHandler = async (context: Context, params: Params) => {
    const { issueId, status, name } = params
    const projectId = await context.stateManager.getProjectId()

    const updateData: { status?: typeof status; name?: string } = {}
    if (status !== undefined) {
        updateData.status = status
    }
    if (name !== undefined) {
        updateData.name = name
    }

    const result = await context.api.errorTracking({ projectId }).updateIssue({
        issueId,
        data: updateData,
    })

    if (!result.success) {
        throw new Error(`Failed to update issue: ${result.error.message}`)
    }

    return {
        content: [
            {
                type: 'text',
                text: `Successfully updated issue ${issueId}. Updated fields: ${JSON.stringify(result.data, null, 2)}`,
            },
        ],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'update-issue',
    schema,
    handler: updateIssueHandler,
})

export default tool
