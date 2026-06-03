import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

export const NotebookCreateFromMarkdownSchema = z.object({
    title: z
        .string()
        .describe('Notebook title. Also used as the top-level heading if the markdown does not start with one.'),
    markdown_content: z
        .string()
        .describe(
            'Canonical notebook markdown. Use normal markdown for prose. Embed queries with `<Query>...</Query>` blocks containing query JSON. Embed resources with self-closing tags such as `<FeatureFlag id="12" />`, `<Experiment id="34" />`, `<Survey id="uuid" />`, `<Cohort id="12" />`, `<Person id="uuid" />`, `<Group id="12" />`, and `<SessionReplay id="session-id" />`.'
        ),
})

type Params = z.infer<typeof NotebookCreateFromMarkdownSchema>

export const createFromMarkdownHandler: ToolBase<
    typeof NotebookCreateFromMarkdownSchema,
    WithPostHogUrl<Schemas.Notebook>
>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()
    const result = await context.api.request<Schemas.Notebook>({
        method: 'POST',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/notebooks/`,
        body: {
            title: params.title,
            content_storage: 'markdown',
            markdown_content: params.markdown_content,
        },
    })
    return await withPostHogUrl(context, result, `/notebooks/${result.short_id}`)
}

const tool = (): ToolBase<typeof NotebookCreateFromMarkdownSchema, WithPostHogUrl<Schemas.Notebook>> => ({
    name: 'notebooks-create-from-markdown',
    schema: NotebookCreateFromMarkdownSchema,
    handler: createFromMarkdownHandler,
})

export default tool
