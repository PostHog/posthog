import type { z } from 'zod'

import { buildActiveEnvironmentContextPrompt } from '@/lib/instructions'
import { ProjectSetActiveSchema } from '@/schema/tool-inputs'
import type { CachedOrg, CachedProject, CachedUser, Context, ToolBase } from '@/tools/types'

const schema = ProjectSetActiveSchema

type Params = z.infer<typeof schema>

type Result = { content: Array<{ type: string; text: string }> }

export const setActiveHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { projectId } = params
    const projectIdStr = projectId.toString()

    await context.cache.set('projectId', projectIdStr)

    // Fetch fresh project data and cache it
    let project: CachedProject | undefined
    const projectResult = await context.api.projects().get({ projectId: projectIdStr })
    if (projectResult.success) {
        project = projectResult.data
        await context.cache.set(`cachedProject:${projectIdStr}` as const, project)
        await context.cache.set(`cachedProjectFetchedAt:${projectIdStr}` as const, Date.now())
    }

    // Read cached user and org for full metadata block
    const distinctId = (await context.cache.get('distinctId')) ?? 'unknown'
    const orgId = (await context.cache.get('orgId')) ?? 'unknown'
    const user = (await context.cache.get(`cachedUser:${distinctId}` as const)) as CachedUser | undefined
    const org = (await context.cache.get(`cachedOrg:${orgId}` as const)) as CachedOrg | undefined

    const metadata = buildActiveEnvironmentContextPrompt(user, org, project)
    const text = metadata
        ? `Switched to project ${projectId}.\n\nCurrent context:\n${metadata}`
        : `Switched to project ${projectId}`

    return {
        content: [{ type: 'text', text }],
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'switch-project',
    schema,
    handler: setActiveHandler,
})

export default tool
